from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_create_agent_inherits_parent_and_sends_initial_prompt(monkeypatch):
    from backend.apps.agents.agents import create_agent
    from backend.apps.agents.models import AgentSession

    parent = AgentSession(
        id="parent-123",
        name="Parent",
        model="sonnet",
        mode="agent",
        system_prompt="Parent system prompt",
        allowed_tools=["Read", "Edit", "Write"],
        dashboard_id="dash-1",
        cwd="/tmp/parent",
    )
    parent.provider = "anthropic"

    created = SimpleNamespace(
        id="child-456",
        parent_session_id=None,
        is_persistent=False,
        model_dump=lambda mode="json": {
            "id": "child-456",
            "parent_session_id": "parent-123",
            "is_persistent": True,
            "mode": "agent",
        },
    )

    captured_config = {}

    async def fake_launch_agent(config):
        captured_config["config"] = config
        return created

    send_message = AsyncMock()

    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.get_session", lambda session_id: parent)
    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.resume_session", AsyncMock())
    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.launch_agent", fake_launch_agent)
    monkeypatch.setattr("backend.apps.agents.agent_manager.agent_manager.send_message", send_message)

    result = await create_agent({
        "sender_session_id": "parent-123",
        "prompt": "Draft a plan for the next step.",
        "persistent": True,
        "name": "Child",
    })

    config = captured_config["config"]
    assert config.parent_session_id == "parent-123"
    assert config.is_persistent is True
    assert config.system_prompt == "Parent system prompt"
    assert config.allowed_tools == ["Read", "Edit", "Write"]
    assert send_message.await_count == 1
    assert send_message.await_args.args[1] == "Draft a plan for the next step."
    assert result["session_id"] == "child-456"
    assert result["session"]["is_persistent"] is True