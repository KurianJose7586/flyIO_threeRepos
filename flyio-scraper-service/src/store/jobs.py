"""
In-memory job store.

Holds all job state for the lifetime of the service process.
If the service restarts, all jobs are lost — this is intentional.
flyio-admin is responsible for re-triggering jobs if needed.

Jobs are keyed by job_id (UUID string) in a module-level dict.
Thread-safe reads are fine (GIL); no concurrent writes to the same
job happen by design (one worker coroutine processes one job at a time).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


JobStatus = Literal["pending", "success", "failed"]
JobType   = Literal["urls", "sources"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id:       str
    type:         JobType
    status:       JobStatus       = "pending"
    submitted_at: str             = field(default_factory=_utcnow)
    completed_at: str | None      = None
    results:      list[dict] | None = None   # list of chunk dicts once done
    error:        str | None      = None     # error message if status == "failed"

    def to_dict(self) -> dict:
        """Serialise to a plain dict safe for JSON response."""
        return {
            "job_id":       self.job_id,
            "type":         self.type,
            "status":       self.status,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "results":      self.results,
            "error":        self.error,
        }


# ── Module-level store — lives for the lifetime of the process ───────────────
_store: dict[str, Job] = {}


class JobIdConflictError(Exception):
    """Raised when a caller supplies a job_id that is already in the store."""


def create_job(job_type: JobType, job_id: str | None = None) -> Job:
    """Create a new job in pending state and add it to the store.

    `job_id` lets the caller supply its own correlation ID instead of having
    one minted here. flyio-admin creates a UUID per scrape operation, records
    it in its own `jobs` table, and then polls GET /scrape/jobs/{id} with it —
    its migration 004 describes this as "a UUID job_id that flows through both
    this service and flyio-scraper-service". Until this parameter existed the
    ID could not actually flow: this service always generated its own, so every
    poll from Admin 404'd until its 300s timeout and the whole ingestion
    pipeline failed with a successful crawl sitting unread in memory.

    Raises JobIdConflictError rather than overwriting an existing job — a
    silent overwrite would strand whoever was polling the original.
    """
    if job_id is not None:
        if job_id in _store:
            raise JobIdConflictError(job_id)
        new_id = job_id
    else:
        new_id = str(uuid.uuid4())

    job = Job(job_id=new_id, type=job_type)
    _store[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    """Return the job or None if not found."""
    return _store.get(job_id)


def update_job(job_id: str, **kwargs: Any) -> None:
    """Update one or more fields on an existing job."""
    job = _store.get(job_id)
    if job is None:
        return
    for key, value in kwargs.items():
        setattr(job, key, value)
