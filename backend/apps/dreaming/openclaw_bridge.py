from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any


_COMMON_OPENCLAW_PATHS = [
    "~/Development/openclaw/openclaw.mjs",
    "~/Development/openclaw/bin/openclaw",
    "~/Development/openclaw/node_modules/.bin/openclaw",
    "~/dev/openclaw/openclaw.mjs",
    "~/projects/openclaw/openclaw.mjs",
    "~/github/openclaw/openclaw.mjs",
    "/usr/local/bin/openclaw",
    "/opt/homebrew/bin/openclaw",
]

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|token|bearer|authorization|secret|password|cookie|set-cookie|session)",
    re.IGNORECASE,
)

_SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
]


def _is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _is_openclaw_mjs(path: str) -> bool:
    return os.path.isfile(path) and os.path.basename(path) == "openclaw.mjs"


def _normalize_candidate(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _validate_openclaw_path(path: str | None) -> str | None:
    if not path:
        return None
    candidate = _normalize_candidate(path)
    if _is_executable_file(candidate) or _is_openclaw_mjs(candidate):
        return candidate
    resolved = shutil.which(path)
    if resolved:
        return os.path.abspath(resolved)
    return None


def detect_openclaw_path(existing: str | None = None) -> tuple[str | None, str]:
    """Best-effort OpenClaw path discovery.

    Order:
    1) User-provided existing path, if valid
    2) `which openclaw`
    3) Common installation paths
    """
    valid_existing = _validate_openclaw_path(existing)
    if valid_existing:
        return valid_existing, f"OpenClaw detected at {valid_existing}."

    which_path = shutil.which("openclaw")
    if which_path:
        resolved = _validate_openclaw_path(which_path)
        if resolved:
            return resolved, f"OpenClaw detected via PATH at {resolved}."

    for candidate in _COMMON_OPENCLAW_PATHS:
        resolved = _validate_openclaw_path(candidate)
        if resolved:
            return resolved, f"OpenClaw detected at {resolved}."

    return None, (
        "OpenClaw was not found. Dreaming will stay idle until OpenClaw is installed "
        "or a valid OpenClaw path is configured."
    )


def ensure_openclaw_path(path: str | None, auto_detect: bool = True) -> tuple[str | None, str]:
    resolved = _validate_openclaw_path(path)
    if resolved:
        return resolved, f"OpenClaw path is configured: {resolved}."
    if auto_detect:
        return detect_openclaw_path(existing=None)
    return None, (
        "Configured OpenClaw path is invalid and auto-detect is disabled. "
        "Dreaming is unavailable until the path is fixed."
    )


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)

    # Generic key/value redaction for log-like snippets.
    redacted = re.sub(
        r"(?i)(api[_-]?key|token|bearer|authorization|secret|password)\s*[:=]\s*[^\s,;\]\}\)]+",
        r"\1=[REDACTED]",
        redacted,
    )
    return redacted


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, inner in value.items():
            if _SENSITIVE_KEY_PATTERN.search(str(key)):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = _sanitize_payload(inner)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _format_message_line(role: str, content: Any) -> str:
    sanitized = _sanitize_payload(content)
    if isinstance(sanitized, str):
        text = sanitized.strip()
    else:
        text = json.dumps(sanitized, ensure_ascii=True)
    if len(text) > 2000:
        text = text[:2000] + "..."
    return f"{role}: {text}"


def _openclaw_state_root() -> str:
    custom_root = os.environ.get("OPENCLAW_HOME", "").strip()
    if custom_root:
        return _normalize_candidate(custom_root)
    return _normalize_candidate("~/.openclaw")


def _session_corpus_dir() -> str:
    return os.path.join(_openclaw_state_root(), "workspace", "memory", ".dreams", "session-corpus")


def export_session_to_openclaw_corpus(session_id: str, session_doc: dict[str, Any]) -> tuple[bool, str]:
    messages = session_doc.get("messages") or []
    if not messages:
        return False, "No messages to export for dreaming corpus."

    corpus_dir = _session_corpus_dir()
    os.makedirs(corpus_dir, exist_ok=True)

    now = datetime.utcnow()
    file_path = os.path.join(corpus_dir, f"{now.strftime('%Y-%m-%d')}.txt")
    created_at = session_doc.get("created_at") or now.isoformat()
    status = session_doc.get("status") or "unknown"

    lines: list[str] = []
    lines.append(f"Session: {session_id}")
    lines.append(f"Created: {created_at}")
    lines.append(f"Status: {status}")

    for message in messages:
        role = str(message.get("role") or "unknown").lower()
        if role not in {"user", "assistant", "system", "thinking", "tool_call", "tool_result"}:
            continue
        lines.append(_format_message_line(role, message.get("content")))

    if len(lines) <= 3:
        return False, "No exportable conversation content found."

    payload = "\n".join(lines) + "\n\n"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(payload)

    return True, f"Exported session {session_id} to OpenClaw corpus at {file_path}."


def _build_openclaw_command(openclaw_path: str, args: list[str]) -> list[str]:
    if os.path.basename(openclaw_path) == "openclaw.mjs":
        return ["node", openclaw_path, *args]
    return [openclaw_path, *args]


def run_openclaw_dreaming_cycle(openclaw_path: str) -> tuple[bool, str]:
    """Trigger OpenClaw memory promotion/rem reflection in a single cycle."""
    try:
        promote_cmd = _build_openclaw_command(openclaw_path, ["memory", "promote", "--apply"])
        promote = subprocess.run(promote_cmd, capture_output=True, text=True, timeout=180)
        if promote.returncode != 0:
            stderr = (promote.stderr or "").strip()
            return False, f"OpenClaw dreaming failed during promote: {stderr or 'unknown error'}"

        rem_cmd = _build_openclaw_command(openclaw_path, ["memory", "rem-harness"])
        rem = subprocess.run(rem_cmd, capture_output=True, text=True, timeout=180)
        if rem.returncode != 0:
            stderr = (rem.stderr or "").strip()
            return False, f"OpenClaw dreaming promote succeeded but rem-harness failed: {stderr or 'unknown error'}"

        promote_out = (promote.stdout or "").strip()
        rem_out = (rem.stdout or "").strip()
        summary = " | ".join(part for part in [promote_out, rem_out] if part)
        if not summary:
            summary = "OpenClaw dreaming cycle completed."
        return True, summary
    except FileNotFoundError:
        return False, "OpenClaw executable was not found."
    except subprocess.TimeoutExpired:
        return False, "OpenClaw dreaming cycle timed out."
    except Exception as e:  # pragma: no cover - defensive
        return False, f"OpenClaw dreaming cycle failed: {e}"
