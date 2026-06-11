"""In-memory job manager for background download and research tasks."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: str
    type: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    # Language-neutral message identifier + params; the frontend resolves these
    # via its i18n layer so progress text is never hard-coded to one language.
    message_code: str = ""
    message_params: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "message_code": self.message_code,
            "message_params": self.message_params,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_type: str) -> str:
        job_id = str(uuid4())
        with self._lock:
            self._jobs[job_id] = Job(id=job_id, type=job_type)
        return job_id

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        message: str | None = None,
        message_code: str | None = None,
        message_params: dict[str, Any] | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if message is not None:
                job.message = message
            if message_code is not None:
                job.message_code = message_code
                job.message_params = message_params or {}
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            job.updated_at = time.time()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_dict(self, job_id: str) -> dict[str, Any] | None:
        job = self.get(job_id)
        return job.to_dict() if job else None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs[:limit]]


job_manager = JobManager()
