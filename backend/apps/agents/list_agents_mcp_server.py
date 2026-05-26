#!/usr/bin/env python3
"""
Stdio MCP server that exposes a simple ListAgents tool.

Returns a human-readable list of sessions visible to the dashboard (name, id, status).
"""

import json
import os
import sys
import urllib.error
import urllib.request

BACKEND_PORT = os.environ.get("OPENSWARM_PORT", "8324")
BACKEND_AUTH = os.environ.get("OPENSWARM_AUTH_TOKEN", "")
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/agents/sessions"
PARENT_SESSION_ID = os.environ.get("OPENSWARM_PARENT_SESSION_ID", "")
DASHBOARD_ID = os.environ.get("OPENSWARM_DASHBOARD_ID", "")

TOOLS = [
    {
        "name": "ListAgents",
        "description": "List agent sessions visible to this dashboard (name, session id, status)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dashboard_id": {"type": "string", "description": "Optional dashboard id to filter visible sessions."},
            },
            "additionalProperties": False,
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


def call_backend(dashboard_id: str | None) -> dict:
    url = BACKEND_URL
    if dashboard_id:
        url = f"{BACKEND_URL}?dashboard_id={urllib.request.quote(dashboard_id)}"
    elif DASHBOARD_ID:
        url = f"{BACKEND_URL}?dashboard_id={urllib.request.quote(DASHBOARD_ID)}"

    headers = {"Content-Type": "application/json"}
    if BACKEND_AUTH:
        headers["Authorization"] = f"Bearer {BACKEND_AUTH}"
    req = urllib.request.Request(url, data=None, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def format_sessions(sessions: list[dict]) -> str:
    if not sessions:
        return "(no sessions)"
    lines = []
    for s in sessions:
        name = s.get("name") or "(untitled)"
        sid = s.get("id") or s.get("session_id") or ""
        status = s.get("status") or s.get("state") or s.get("status_text") or ""
        lines.append(f"- {name} (session: {sid}) [{status}]")
    return "\n".join(lines)


def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    if tool_name != "ListAgents":
        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    dashboard_id = arguments.get("dashboard_id") or DASHBOARD_ID or None
    result = call_backend(dashboard_id)
    if "error" in result:
        return {"content": [{"type": "text", "text": f"Error: {result['error']}"}], "isError": True}

    sessions = result if isinstance(result, list) else result.get("sessions") or result.get("items") or []
    body = format_sessions(sessions)
    return {"content": [{"type": "text", "text": body}]}


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
                    "name": "openswarm-list-agents",
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
            try:
                result = handle_tool_call(tool_name, arguments)
                send_response(id_, result)
            except Exception as e:
                send_response(id_, error={"code": -32000, "message": str(e)})
        elif method == "ping":
            send_response(id_, {})
        elif id_ is not None:
            send_response(id_, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
