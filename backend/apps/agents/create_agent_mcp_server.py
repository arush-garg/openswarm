#!/usr/bin/env python3
"""
Stdio MCP server that exposes the backend-owned CreateAgent tool.

This avoids the native CLI Agent tool path, which spawns a subprocess-based
child agent and can fail before OpenSwarm can apply its persistence rules.
The backend route creates the session directly, then sends the initial goal
message as a normal turn.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BACKEND_PORT = os.environ.get("OPENSWARM_PORT", "8324")
BACKEND_AUTH = os.environ.get("OPENSWARM_AUTH_TOKEN", "")
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/agents/create"
PARENT_SESSION_ID = os.environ.get("OPENSWARM_PARENT_SESSION_ID", "")
DASHBOARD_ID = os.environ.get("OPENSWARM_DASHBOARD_ID", "")

TOOLS = [
    {
        "name": "CreateAgent",
        "description": (
            "Create a new agent session. Use persistence='persistent' or persistent=true "
            "to make it persistent and routable; omit the flag for a temporary subagent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional agent name."},
                "prompt": {"type": "string", "description": "The first task or goal for the new agent."},
                "system_prompt": {"type": "string", "description": "Optional system prompt to apply to the new agent."},
                "model": {"type": "string", "description": "Optional model override."},
                "provider": {"type": "string", "description": "Optional provider override."},
                "mode": {"type": "string", "description": "Optional session mode override."},
                "persistence": {"type": "string", "description": "Use 'persistent' for a persistent agent."},
                "persistent": {"type": "boolean", "description": "True to create a persistent agent."},
                "context_paths": {"type": "array", "items": {"type": "object"}},
                "attached_skills": {"type": "array", "items": {"type": "object"}},
                "forced_tools": {"type": "array", "items": {"type": "string"}},
                "selected_browser_ids": {"type": "array", "items": {"type": "string"}},
                "images": {"type": "array", "items": {"type": "object"}},
                "client_message_id": {"type": "string"},
                "dashboard_id": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
]


def send_response(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def call_backend(arguments: dict) -> dict:
    payload = dict(arguments)
    payload["parent_session_id"] = PARENT_SESSION_ID
    payload.setdefault("dashboard_id", DASHBOARD_ID)
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if BACKEND_AUTH:
        headers["Authorization"] = f"Bearer {BACKEND_AUTH}"
    req = urllib.request.Request(
        BACKEND_URL,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    if tool_name != "CreateAgent":
        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    if not arguments.get("prompt"):
        return {"content": [{"type": "text", "text": "Error: prompt is required"}], "isError": True}

    result = call_backend(arguments)
    if "error" in result:
        return {"content": [{"type": "text", "text": f"Error: {result['error']}"}], "isError": True}

    session_id = result.get("session_id", "")
    session = result.get("session", {})
    label = session.get("name") or arguments.get("name") or "Agent"
    persistent = session.get("is_persistent", False)
    lines = [f"**Created Agent** (session: {session_id})", f"Name: {label}", f"Persistent: {persistent}"]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        id_ = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            send_response(id_, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "openswarm-create-agent",
                    "version": "1.0.0",
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send_response(id_, {"tools": TOOLS})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool_call(tool_name, arguments)
            send_response(id_, result)
        elif method == "ping":
            send_response(id_, {})
        elif id_ is not None:
            send_response(id_, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()