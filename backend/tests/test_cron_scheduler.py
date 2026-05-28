from __future__ import annotations

import importlib

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

cron_mod = importlib.import_module("backend.apps.cron.cron")


@pytest.mark.asyncio
async def test_cron_job_create_list_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_mod, "CRON_JOBS_DIR", str(tmp_path))
    cron_mod._run_locks.clear()

    job = await cron_mod.create_cron_job(
        cron_mod.CronCreateRequest(
            session_id="session-1",
            prompt="Poll Discord #task",
            cron="*/1 * * * *",
        )
    )

    assert job.id
    assert job.human_schedule == "Every minute"
    assert (tmp_path / f"{job.id}.json").exists()

    jobs = await cron_mod.list_cron_jobs()
    assert len(jobs) == 1
    assert jobs[0].session_id == "session-1"

    await cron_mod.delete_cron_job(job.id)
    assert await cron_mod.list_cron_jobs() == []


@pytest.mark.asyncio
async def test_due_cron_job_dispatches_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_mod, "CRON_JOBS_DIR", str(tmp_path))
    cron_mod._run_locks.clear()

    dispatch = AsyncMock()
    monkeypatch.setattr(cron_mod.agent_manager, "get_session", lambda session_id: object())
    monkeypatch.setattr(cron_mod.agent_manager, "resume_session", AsyncMock())
    monkeypatch.setattr(cron_mod.agent_manager, "send_message", dispatch)

    job = await cron_mod.create_cron_job(
        cron_mod.CronCreateRequest(
            session_id="session-2",
            prompt="Check #task and route messages",
            cron="*/1 * * * *",
        )
    )

    stored = cron_mod._load_job(job.id)
    stored.next_run_at = datetime.now().astimezone() - timedelta(minutes=1)
    cron_mod._save_job(stored)

    processed = await cron_mod.run_due_jobs_once()

    assert processed == 1
    dispatch.assert_awaited_once()
    args, kwargs = dispatch.await_args
    assert args[0] == "session-2"
    assert args[1] == "Check #task and route messages"
    assert kwargs["hidden"] is True


@pytest.mark.asyncio
async def test_due_cron_job_uses_communication_agent_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_mod, "CRON_JOBS_DIR", str(tmp_path))
    cron_mod._run_locks.clear()

    fake_session = type(
        "Session",
        (),
        {"id": "session-3", "dashboard_id": "dash-1", "model": "sonnet", "provider": "anthropic"},
    )()
    template_session = type("Template", (), {"id": "template-1"})()
    launch = AsyncMock(return_value=template_session)
    invoke = AsyncMock(return_value={"forked_session_id": "fork-1", "response": "done"})
    send = AsyncMock()

    monkeypatch.setattr(cron_mod.agent_manager, "get_session", lambda session_id: fake_session)
    monkeypatch.setattr(cron_mod.agent_manager, "resume_session", AsyncMock())
    monkeypatch.setattr(cron_mod.agent_manager, "launch_agent", launch)
    monkeypatch.setattr(cron_mod.agent_manager, "invoke_agent", invoke)
    monkeypatch.setattr(cron_mod.agent_manager, "send_message", send)
    monkeypatch.setattr(cron_mod, "_load_communication_agent_prompt", lambda: "communication prompt")

    job = await cron_mod.create_cron_job(
        cron_mod.CronCreateRequest(
            session_id="session-3",
            prompt="COMMUNICATION AGENT DUTY: Poll Discord #task channel and route tasks.",
            cron="*/1 * * * *",
            workflow="discord-communication",
        )
    )

    stored = cron_mod._load_job(job.id)
    stored.next_run_at = datetime.now().astimezone() - timedelta(minutes=1)
    cron_mod._save_job(stored)

    processed = await cron_mod.run_due_jobs_once()

    assert processed == 1
    launch.assert_awaited_once()
    launch_config = launch.await_args.args[0]
    assert launch_config.dashboard_id == "dash-1"
    assert launch_config.active_mcps == ["discord"]
    assert launch_config.system_prompt == "communication prompt"
    invoke.assert_awaited_once_with(
        "template-1",
        job.prompt,
        parent_session_id="session-3",
        dashboard_id="dash-1",
    )
    send.assert_not_awaited()
