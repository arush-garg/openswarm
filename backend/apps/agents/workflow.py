import os
import json
import logging
from datetime import datetime
from uuid import uuid4
from typing import Optional, Dict, Any, List

from backend.config.paths import TASKS_DIR

logger = logging.getLogger(__name__)


def _ensure_tasks_dir() -> None:
    os.makedirs(TASKS_DIR, exist_ok=True)


class TaskEnvelope:
    def __init__(
        self,
        sender: str,
        recipient: str,
        payload: dict,
        mode: str = "async",
        task_id: str | None = None,
    ):
        self.id = task_id or uuid4().hex
        self.sender = sender
        self.recipient = recipient
        self.mode = mode  # 'sync' or 'async'
        self.payload = payload
        self.status = "queued"
        self.result: Optional[dict] = None
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "mode": self.mode,
            "payload": self.payload,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskEnvelope":
        t = cls(d.get("sender", ""), d.get("recipient", ""), d.get("payload", {}), d.get("mode", "async"))
        t.id = d.get("id", t.id)
        t.status = d.get("status", t.status)
        t.result = d.get("result")
        t.created_at = d.get("created_at", t.created_at)
        t.updated_at = d.get("updated_at", t.updated_at)
        return t


def persist_task(task: TaskEnvelope) -> None:
    _ensure_tasks_dir()
    path = os.path.join(TASKS_DIR, f"{task.id}.json")
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(task.model_dump(), f, indent=2)
        os.replace(tmp, path)
    except Exception:
        logger.exception("Failed to persist task %s", task.id)


def load_task(task_id: str) -> Optional[TaskEnvelope]:
    path = os.path.join(TASKS_DIR, f"{task_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return TaskEnvelope.from_dict(data)
    except Exception:
        logger.exception("Failed to load task %s", task_id)
        return None


def list_tasks(recipient: str | None = None, statuses: set[str] | None = None) -> List[TaskEnvelope]:
    _ensure_tasks_dir()
    out: List[TaskEnvelope] = []
    for fname in os.listdir(TASKS_DIR):
        if not fname.endswith(".json"): 
            continue
        try:
            with open(os.path.join(TASKS_DIR, fname)) as f:
                d = json.load(f)
            if recipient is not None and d.get("recipient") != recipient:
                continue
            if statuses is not None and d.get("status") not in statuses:
                continue
            out.append(TaskEnvelope.from_dict(d))
        except Exception:
            logger.exception("Failed reading task file %s", fname)
    out.sort(key=lambda t: (t.created_at or "", t.id))
    return out


def list_queued_for_recipient(recipient: str) -> List[TaskEnvelope]:
    return list_tasks(recipient=recipient, statuses={"queued", "processing"})


def update_task_status(task_id: str, status: str) -> bool:
    t = load_task(task_id)
    if not t:
        return False
    t.status = status
    t.updated_at = datetime.now().isoformat()
    persist_task(t)
    return True


def claim_task(task_id: str, recipient: str | None = None) -> Optional[TaskEnvelope]:
    t = load_task(task_id)
    if not t:
        return None
    if recipient is not None and t.recipient != recipient:
        return None
    if t.status not in ("queued", "processing"):
        return None
    t.status = "processing"
    t.updated_at = datetime.now().isoformat()
    persist_task(t)
    return t


def update_task_result(task_id: str, result: dict, status: str = "completed") -> bool:
    t = load_task(task_id)
    if not t:
        return False
    t.result = result
    t.status = status
    t.updated_at = datetime.now().isoformat()
    persist_task(t)
    return True
