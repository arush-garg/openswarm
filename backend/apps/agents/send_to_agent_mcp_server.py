#!/usr/bin/env python3
"""
Stdio MCP server that exposes the SendToAgent tool.

Routes a message to another (persistent) agent session via the OpenSwarm
backend. Intended for agent-to-agent routing, not for cloning a session.
"""

import json
import os
import sys
import urllib.request
import urllib.error

BACKEND_PORT = os.environ.get("OPENSWARM_PORT", "8324")
BACKEND_AUTH = os.environ.get("OPENSWARM_AUTH_TOKEN", "")
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/agents/route"
PARENT_SESSION_ID = os.environ.get("OPENSWARM_PARENT_SESSION_ID", "")
DASHBOARD_ID = os.environ.get("OPENSWARM_DASHBOARD_ID", "")

TOOLS = [
    {
        "name": "SendToAgent",
        "description": (
            "Route a message to another persistent agent session. "
            "Use this to hand off work or request input from another agent "
            "without forking its history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session ID of the target persistent agent.",
                },
                "message": {
                    "type": "string",
                    "description": "The message/task to send to the target agent.",
                },
                "mode": {
                    "type": "string",
                    "description": "Optional mode override for the target agent.",
                },
            },
            "required": ["session_id", "message"],
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


def call_backend(session_id: str, message: str, mode: str | None = None) -> dict:
    payload = {
        "sender_session_id": PARENT_SESSION_ID,
        "target_session_id": session_id,
        "prompt": message,
        "dashboard_id": DASHBOARD_ID,
    }
    if mode:
        payload["mode"] = mode
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
    if tool_name != "SendToAgent":
        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    session_id = arguments.get("session_id", "")
    message = arguments.get("message", "")
    mode = arguments.get("mode")

    if not session_id:
        return {"content": [{"type": "text", "text": "Error: session_id is required"}], "isError": True}
    if not message:
        return {"content": [{"type": "text", "text": "Error: message is required"}], "isError": True}

    result = call_backend(session_id, message, mode=mode)

    if "error" in result:
        return {"content": [{"type": "text", "text": f"Error: {result['error']}"}], "isError": True}

    target_id = result.get("target_session_id", session_id)
    status = result.get("status", "sent")

    lines = [f"**Routed to Agent** (session: {target_id})", f"Status: {status}"]
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
                    "name": "openswarm-send-to-agent",
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
