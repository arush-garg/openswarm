from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from pydantic_extra_types.cron import CronStr

from backend.apps.agents.agent_manager import agent_manager
from backend.apps.agents.core.models import AgentConfig
from backend.config.Apps import SubApp
from backend.config.paths import CRON_JOBS_DIR

logger = logging.getLogger(__name__)

_cron_task: asyncio.Task | None = None
_run_locks: dict[str, asyncio.Lock] = {}


class CronJob(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(default_factory=lambda: uuid4().hex)
    name: Optional[str] = None
    session_id: str
    prompt: str
    cron: CronStr
    workflow: Optional[str] = None
    timezone: Optional[str] = None
    recurring: bool = True
    enabled: bool = True
    durable: bool = True
    human_schedule: str = "Cron schedule"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    run_count: int = 0
    last_error: Optional[str] = None


class CronCreateRequest(BaseModel):
    session_id: str
    prompt: str
    cron: str
    name: Optional[str] = None
    workflow: Optional[str] = None
    timezone: Optional[str] = None
    recurring: bool = True
    enabled: bool = True
    durable: bool = True


class CronDeleteRequest(BaseModel):
    id: str


class CronListResponse(BaseModel):
    jobs: list[CronJob]


def _ensure_dir() -> None:
    os.makedirs(CRON_JOBS_DIR, exist_ok=True)


def _job_path(job_id: str) -> str:
    return os.path.join(CRON_JOBS_DIR, f"{job_id}.json")


def _load_job_from_path(path: str) -> CronJob:
    with open(path) as f:
        data = json.load(f)
    return CronJob.model_validate(data)


def _save_job(job: CronJob) -> None:
    _ensure_dir()
    payload = job.model_dump(mode="json")
    payload["cron"] = str(job.cron)
    payload["next_run_at"] = job.next_run_at.isoformat() if job.next_run_at else None
    payload["last_run_at"] = job.last_run_at.isoformat() if job.last_run_at else None
    tmp_path = f"{_job_path(job.id)}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, _job_path(job.id))


def _load_job(job_id: str) -> CronJob:
    path = _job_path(job_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Cron job not found")
    return _load_job_from_path(path)


def _list_jobs_raw() -> list[CronJob]:
    _ensure_dir()
    jobs: list[CronJob] = []
    for fname in os.listdir(CRON_JOBS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(CRON_JOBS_DIR, fname)
        try:
            jobs.append(_load_job_from_path(path))
        except Exception:
            logger.exception("Failed to load cron job file %s", fname)
    jobs.sort(key=lambda job: ((job.next_run_at or job.updated_at).isoformat(), job.id))
    return jobs


def _humanize_cron(expr: str) -> str:
    parts = expr.split()
    if len(parts) == 5 and parts[1:] == ["*", "*", "*", "*"]:
        minute = parts[0]
        if minute == "*":
            return "Every minute"
        if minute.startswith("*/"):
            try:
                step = int(minute[2:])
                return "Every minute" if step == 1 else f"Every {step} minutes"
            except ValueError:
                pass
    if expr == "0 * * * *":
        return "Hourly"
    return f"Cron schedule ({expr})"


def _next_run_for(expr: str, timezone: str | None, after: datetime | None = None) -> datetime:
    cron = CronStr(expr)
    start = after or datetime.now().astimezone()
    return cron.next_after(start_date=start, timezone_str=timezone)


COMMUNICATION_AGENT_PROMPT_FILE = Path(__file__).with_name("communication_agent.md")
COMMUNICATION_AGENT_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Grep",
    "ListAgents",
    "InvokeAgent",
    "SendToAgent",
    "AskUserQuestion",
]
COMMUNICATION_AGENT_ACTIVE_MCPS = ["discord"]


def _load_communication_agent_prompt() -> str:
    with open(COMMUNICATION_AGENT_PROMPT_FILE) as f:
        return f.read().strip()


def _is_communication_workflow(job: CronJob) -> bool:
    if (job.workflow or "").strip().lower() == "discord-communication":
        return True
    prompt = (job.prompt or "").lower()
    return "communication agent duty" in prompt and "discord" in prompt and "task channel" in prompt


async def _launch_communication_agent(session):
    config = AgentConfig(
        name="Communication Agent",
        model=session.model,
        mode="agent",
        provider=session.provider,
        system_prompt=_load_communication_agent_prompt(),
        allowed_tools=list(COMMUNICATION_AGENT_ALLOWED_TOOLS),
        active_mcps=list(COMMUNICATION_AGENT_ACTIVE_MCPS),
        dashboard_id=session.dashboard_id,
        parent_session_id=session.id,
        is_persistent=False,
    )
    return await agent_manager.launch_agent(config)


async def _resume_session(session_id: str):
    session = agent_manager.get_session(session_id)
    if session:
        return session
    try:
        return await agent_manager.resume_session(session_id)
    except Exception:
        return None


async def _fire_job(job: CronJob) -> None:
    session = await _resume_session(job.session_id)
    if not session:
        raise RuntimeError(f"Session {job.session_id} not available")

    if _is_communication_workflow(job):
        template = await _launch_communication_agent(session)
        await agent_manager.invoke_agent(
            template.id,
            job.prompt,
            parent_session_id=job.session_id,
            dashboard_id=session.dashboard_id,
        )
        return

    await agent_manager.send_message(
        job.session_id,
        job.prompt,
        hidden=True,
    )


async def _run_job(job: CronJob) -> None:
    lock = _run_locks.setdefault(job.id, asyncio.Lock())
    if lock.locked():
        return

    async with lock:
        current = None
        try:
            current = _load_job(job.id)
        except HTTPException:
            return

        if not current.enabled or not current.next_run_at:
            return

        now = datetime.now(current.next_run_at.tzinfo) if current.next_run_at.tzinfo else datetime.now().astimezone()
        if current.next_run_at > now:
            return

        try:
            await _fire_job(current)
            current.last_error = None
        except Exception as exc:
            current.last_error = str(exc)
            logger.exception("Cron job %s failed", current.id)
        finally:
            current.last_run_at = now
            current.run_count += 1
            current.updated_at = datetime.now().astimezone()

            if current.recurring and current.enabled:
                try:
                    current.next_run_at = _next_run_for(current.cron, current.timezone, after=now)
                except Exception as exc:
                    current.enabled = False
                    current.last_error = f"Failed to compute next run: {exc}"
            else:
                current.enabled = False
                current.next_run_at = None

            _save_job(current)


async def run_due_jobs_once() -> int:
    jobs = _list_jobs_raw()
    due = [job for job in jobs if job.enabled and job.next_run_at]
    now_count = 0
    for job in due:
        try:
            now = datetime.now(job.next_run_at.tzinfo) if job.next_run_at.tzinfo else datetime.now().astimezone()
            if job.next_run_at <= now:
                now_count += 1
                await _run_job(job)
        except Exception:
            logger.exception("Error while processing cron job %s", job.id)
    return now_count


async def create_cron_job(body: CronCreateRequest) -> CronJob:
    job = CronJob(
        name=body.name,
        session_id=body.session_id,
        prompt=body.prompt,
        cron=CronStr(body.cron),
        timezone=body.timezone,
        recurring=body.recurring,
        enabled=body.enabled,
        durable=body.durable,
        human_schedule=_humanize_cron(body.cron),
    )
    job.next_run_at = _next_run_for(str(job.cron), job.timezone)
    _save_job(job)
    return job


async def delete_cron_job(job_id: str) -> None:
    path = _job_path(job_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Cron job not found")
    os.remove(path)


async def list_cron_jobs() -> list[CronJob]:
    return _list_jobs_raw()


async def _cron_loop() -> None:
    while True:
        try:
            await run_due_jobs_once()
        except Exception:
            logger.exception("Cron scheduler loop error")
        await asyncio.sleep(15)


@asynccontextmanager
async def cron_lifespan():
    global _cron_task
    _ensure_dir()
    try:
        await run_due_jobs_once()
    except Exception:
        logger.exception("Initial cron sweep failed")
    _cron_task = asyncio.create_task(_cron_loop())
    try:
        yield
    finally:
        if _cron_task:
            _cron_task.cancel()
            try:
                await _cron_task
            except asyncio.CancelledError:
                pass
            _cron_task = None


cron = SubApp("cron", cron_lifespan)


@cron.router.get("/jobs")
async def get_jobs():
    return {"jobs": [job.model_dump(mode="json") for job in await list_cron_jobs()]}


@cron.router.get("/list")
async def list_jobs_alias():
    return await get_jobs()


@cron.router.post("/jobs")
async def post_job(body: CronCreateRequest):
    job = await create_cron_job(body)
    return {
        "id": job.id,
        "humanSchedule": job.human_schedule,
        "recurring": job.recurring,
        "durable": job.durable,
        "job": job.model_dump(mode="json"),
    }


@cron.router.post("/create")
async def create_job_alias(body: CronCreateRequest):
    return await post_job(body)


@cron.router.delete("/jobs/{job_id}")
async def remove_job(job_id: str):
    await delete_cron_job(job_id)
    return {"ok": True}


@cron.router.delete("/delete/{job_id}")
async def remove_job_alias(job_id: str):
    return await remove_job(job_id)
