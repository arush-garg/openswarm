from __future__ import annotations

import json


def test_trusted_bash_commands_round_trip(tmp_path, monkeypatch):
    import backend.apps.tools_lib.tools_lib as tools_lib

    rules_path = tmp_path / "trusted_bash_commands.json"
    monkeypatch.setattr(tools_lib, "TRUSTED_BASH_COMMANDS_PATH", str(rules_path))

    rules = [
        {"kind": "exact", "value": "git status"},
        {"kind": "prefix", "value": "grep -R"},
        {"kind": "type", "value": "ls"},
        {"kind": "exact", "value": "git status"},
        {"kind": "bogus", "value": "ignore me"},
    ]

    tools_lib.save_trusted_bash_commands(rules)
    assert json.loads(rules_path.read_text()) == {
        "rules": [
            {"kind": "exact", "value": "git status"},
            {"kind": "prefix", "value": "grep -R"},
            {"kind": "type", "value": "ls"},
        ],
    }
    assert tools_lib.load_trusted_bash_commands() == [
        {"kind": "exact", "value": "git status"},
        {"kind": "prefix", "value": "grep -R"},
        {"kind": "type", "value": "ls"},
    ]


def test_bash_allowlist_rule_matching(tmp_path, monkeypatch):
    import backend.apps.tools_lib.tools_lib as tools_lib
    import backend.apps.agents.agent_manager as agent_manager

    rules_path = tmp_path / "trusted_bash_commands.json"
    monkeypatch.setattr(tools_lib, "TRUSTED_BASH_COMMANDS_PATH", str(rules_path))

    tools_lib.save_trusted_bash_commands([
        {"kind": "exact", "value": "git status"},
        {"kind": "prefix", "value": "grep -R"},
        {"kind": "type", "value": "ls"},
    ])

    assert agent_manager._match_trusted_bash_command_rule("git status") == {"kind": "exact", "value": "git status"}
    assert agent_manager._match_trusted_bash_command_rule("git status -sb") is None
    assert agent_manager._match_trusted_bash_command_rule("grep -R src .") == {"kind": "prefix", "value": "grep -R"}
    assert agent_manager._match_trusted_bash_command_rule("sudo ls -la /tmp") == {"kind": "type", "value": "ls"}
    assert agent_manager._match_trusted_bash_command_rule("python -m pytest") is None