"""
Async background job queue.

Uses a single asyncio.Queue + one long-running coroutine (worker()).
No Redis, no Celery, no external infrastructure — pure asyncio.

The worker is started once at app startup via FastAPI's lifespan and
runs forever until the process exits. Jobs are processed one at a time
(serial) which is appropriate since crawl4ai itself already uses an
internal asyncio.Semaphore for concurrency control.

Payload shapes:
  urls job:    {"urls": ["https://...", ...]}
  sources job: {"sources": [{source_cfg}, ...]}
"""
import asyncio
from datetime import datetime, timezone

from src.store.jobs import update_job
from src.crawler.wrapper import run_crawl_source, run_crawl_urls

# Module-level queue — one queue for the entire service lifetime
_queue: asyncio.Queue = asyncio.Queue()


def queue_size() -> int:
    """Return the current number of pending items in the queue."""
    return _queue.qsize()


async def enqueue(job_id: str, job_type: str, payload: dict) -> None:
    """Add a job to the background queue (non-blocking)."""
    await _queue.put({"job_id": job_id, "job_type": job_type, "payload": payload})


async def worker() -> None:
    """
    Long-running coroutine that processes jobs from the queue.
    Started once at app startup — never awaited directly.
    Runs until the process exits.
    """
    while True:
        item = await _queue.get()
        job_id   = item["job_id"]
        job_type = item["job_type"]
        payload  = item["payload"]

        try:
            if job_type == "urls":
                results = await run_crawl_urls(payload["urls"])
            else:  # sources
                results: list[dict] = []
                for source_cfg in payload["sources"]:
                    source_chunks = await run_crawl_source(source_cfg)
                    results.extend(source_chunks)

            update_job(
                job_id,
                status="success",
                results=results,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as exc:  # noqa: BLE001
            update_job(
                job_id,
                status="failed",
                error=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        finally:
            _queue.task_done()
