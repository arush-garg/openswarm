import asyncio
import json
import os
import sys
from uuid import uuid4

import pytest

# Ensure project root is importable
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.apps.agents import agent_manager as am_mod
from backend.apps.agents import workflow as wf_mod
from backend.apps.agents.models import AgentConfig, AgentSession


@pytest.mark.asyncio
async def test_worker_enqueue_persists_task(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    old_tasks = wf_mod.TASKS_DIR
    monkeypatch.setattr(wf_mod, "TASKS_DIR", str(tasks_dir))

    mgr = am_mod.AgentManager()

    task = wf_mod.TaskEnvelope(sender="u", recipient="r", payload={"prompt": "hi"})
    ok = await mgr.enqueue_task_for_worker("nonexistent", task)
    assert ok

    fpath = tasks_dir / f"{task.id}.json"
    assert fpath.exists(), f"Task file not created: {fpath}"

    monkeypatch.setattr(wf_mod, "TASKS_DIR", old_tasks)


@pytest.mark.asyncio
async def test_worker_run_updates_task_result(tmp_path, event_loop, monkeypatch):
    # Prepare temp dirs and patch paths
    tasks_dir = tmp_path / "tasks"
    sessions_dir = tmp_path / "sessions"
    tasks_dir.mkdir()
    sessions_dir.mkdir()

    monkeypatch.setattr(wf_mod, "TASKS_DIR", str(tasks_dir))
    monkeypatch.setattr(am_mod, "SESSIONS_DIR", str(sessions_dir))

    # Ensure claude_agent_sdk import fails so _run_mock_agent path is used
    monkeypatch.delitem(sys.modules, "claude_agent_sdk", raising=False)

    # Patch ws_manager used by AgentManager to accept approvals
    class DummyWS:
        async def send_to_session(self, *a, **k):
            return None

        async def send_approval_request(self, session_id, request_id, tool_name, tool_input):
            return {"behavior": "allow"}

    monkeypatch.setattr(am_mod, "ws_manager", DummyWS())

    mgr = am_mod.AgentManager()

    # Launch a session and mark it as a worker
    config = AgentConfig(name="Worker", model="sonnet", mode="agent")
    session = await mgr.launch_agent(config)
    session.is_worker = True
    session.worker_status = "idle"
    mgr.sessions[session.id] = session
    am_mod._save_session(session.id, session.model_dump(mode="json"))

    # Enqueue a task for this worker
    task = wf_mod.TaskEnvelope(sender="u", recipient=session.id, payload={"prompt": "do work"})
    await mgr.enqueue_task_for_worker(session.id, task)

    # Wait for the background task to complete (mock agent sleeps briefly)
    key = f"worker:{session.id}:{task.id}"
    assert key in mgr.tasks
    t = mgr.tasks[key]
    await asyncio.wait_for(t, timeout=10)

    # Verify task was updated to completed
    loaded = wf_mod.load_task(task.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.result and loaded.result.get("success") is True


def test_rehydrate_workers(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    sessions_dir = tmp_path / "sessions"
    tasks_dir.mkdir()
    sessions_dir.mkdir()

    monkeypatch.setattr(wf_mod, "TASKS_DIR", str(tasks_dir))
    monkeypatch.setattr(am_mod, "SESSIONS_DIR", str(sessions_dir))

    # Create a persisted worker session file
    sid = uuid4().hex
    session = AgentSession(id=sid, name="rehyd-test", is_worker=True, worker_status="idle")
    with open(os.path.join(str(sessions_dir), f"{sid}.json"), "w") as f:
        json.dump(session.model_dump(mode="json"), f)

    # Create a queued task file for that worker
    task = wf_mod.TaskEnvelope(sender="u", recipient=sid, payload={"prompt": "rehyd"})
    wf_mod.persist_task(task)

    # New manager should rehydrate the worker into sessions and locks
    mgr = am_mod.AgentManager()
    assert sid in mgr.sessions
    assert sid in mgr.worker_locks
