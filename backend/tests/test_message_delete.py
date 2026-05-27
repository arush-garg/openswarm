from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    import backend.auth as auth_mod

    if not auth_mod._TOKEN:
        import secrets

        auth_mod._TOKEN = secrets.token_urlsafe(32)
    return TestClient(app, headers={"Authorization": f"Bearer {auth_mod._TOKEN}"})


def test_delete_message_removes_it_from_session(client, monkeypatch):
    from backend.apps.agents.core.models import AgentSession, Message

    session = AgentSession(
        id="session-1",
        name="Test",
        model="sonnet",
        mode="agent",
        provider="anthropic",
        allowed_tools=[],
    )
    session.messages = [
        Message(id="msg-1", role="user", content="hello"),
        Message(id="msg-2", role="assistant", content="world"),
    ]

    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.sessions", {session.id: session})
    monkeypatch.setattr("backend.apps.agents.agent_manager._save_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.apps.agents.agent_manager.ws_manager.send_to_session", AsyncMock())

    res = client.delete(f"/api/agents/sessions/{session.id}/messages/msg-1")

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert [m.id for m in session.messages] == ["msg-2"]


def test_delete_message_rejects_branch_anchor(client, monkeypatch):
    from backend.apps.agents.core.models import AgentSession, Message, MessageBranch

    session = AgentSession(
        id="session-2",
        name="Test",
        model="sonnet",
        mode="agent",
        provider="anthropic",
        allowed_tools=[],
    )
    session.messages = [Message(id="msg-1", role="assistant", content="anchor")]
    session.branches = {
        "main": MessageBranch(id="main", parent_branch_id=None, fork_point_message_id=None),
        "fork-1": MessageBranch(id="fork-1", parent_branch_id="main", fork_point_message_id="msg-1"),
    }

    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.sessions", {session.id: session})

    res = client.delete(f"/api/agents/sessions/{session.id}/messages/msg-1")

    assert res.status_code == 409