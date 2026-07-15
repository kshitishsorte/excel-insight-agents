"""
In-memory project store. No database, no disk — everything lives on the
FastAPI process and resets on restart (confirmed acceptable).
"""

from __future__ import annotations

import itertools
import time
import uuid
from threading import RLock
from typing import Literal, Optional

Status = Literal["empty", "queued", "running", "ready", "error"]

_counter = itertools.count(1)


class Project:
    def __init__(self, name: str):
        self.id: str = uuid.uuid4().hex[:12]
        self.name: str = name
        self.created_at: float = time.time()
        self.status: Status = "empty"
        self.messages: list[dict] = []          # {id, role, content, kind, ts}
        self.report: Optional[dict] = None       # serialized report or None
        self.filename: Optional[str] = None
        self.error: Optional[str] = None
        # In-memory export artifacts, built when the pipeline finishes.
        self.cleaned_xlsx: Optional[bytes] = None
        self.report_html: Optional[str] = None
        # The cleaned DataFrame, kept so the chat agent can run real analyses on it.
        self.cleaned_df = None  # pandas.DataFrame | None

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "status": self.status,
            "has_report": self.report is not None,
        }

    def to_full(self) -> dict:
        return {
            **self.to_summary(),
            "filename": self.filename,
            "messages": self.messages,
            "report": self.report,
            "error": self.error,
        }


class ProjectStore:
    def __init__(self):
        self._projects: dict[str, Project] = {}
        self._lock = RLock()

    def create(self, name: Optional[str] = None) -> Project:
        with self._lock:
            if not name:
                name = f"Untitled analysis {next(_counter)}"
            p = Project(name)
            self._projects[p.id] = p
            return p

    def get(self, pid: str) -> Optional[Project]:
        return self._projects.get(pid)

    def list(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.created_at, reverse=True)

    def delete(self, pid: str) -> bool:
        with self._lock:
            return self._projects.pop(pid, None) is not None

    def add_message(
        self,
        pid: str,
        role: str,
        content: str,
        kind: str = "chat",
        analysis: Optional[dict] = None,
    ) -> Optional[dict]:
        """kind: 'chat' | 'status' | 'system'. `analysis` attaches computed results."""
        with self._lock:
            p = self._projects.get(pid)
            if not p:
                return None
            msg = {
                "id": uuid.uuid4().hex[:10],
                "role": role,
                "content": content,
                "kind": kind,
                "ts": time.time(),
            }
            if analysis is not None:
                msg["analysis"] = analysis
            p.messages.append(msg)
            return msg


# Module-level singleton used by the API + websocket layers.
store = ProjectStore()
