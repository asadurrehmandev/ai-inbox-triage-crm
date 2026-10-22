"""APScheduler loop. It polls the mailbox and drains whatever the webhook queued."""

from __future__ import annotations

import logging
import os
import threading
import uuid

from apscheduler.schedulers.background import BackgroundScheduler

from app import db
from app.mailbox import get_mailbox
from app.pipeline import process_pending

logger = logging.getLogger("lane.worker")

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def interval_seconds() -> int:
    raw = os.environ.get("WORKER_INTERVAL_SECONDS", "60").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 60


def worker_enabled() -> bool:
    return os.environ.get("WORKER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def run_once(source: str = "scheduler") -> dict:
    """One pass: pull IMAP if configured, classify every unseen message, file leads."""
    owner = f"{source}-{uuid.uuid4().hex[:8]}"
    if not db.acquire_worker_lock(owner):
        logger.warning("worker_skipped_locked source=%s", source)
        return {"source": source, "processed": 0, "skipped": "locked", "results": []}
    try:
        return _run_locked(source)
    finally:
        db.release_worker_lock(owner)


def _run_locked(source: str) -> dict:
    with _lock:
        started = db.now()
        ingested = 0
        mailbox = get_mailbox()
        if mailbox.name == "imap":
            for message in mailbox.fetch_unseen():
                if not message.get("id"):
                    continue
                try:
                    existed = db.get_email(message["id"]) is not None
                    db.insert_email(message)
                    mailbox.mark_seen(message.get("imap_uid"))
                    if not existed:
                        ingested += 1
                except Exception:
                    logger.warning("imap_store_failed id=%s", message.get("id"), exc_info=True)
        results = process_pending()
        finished = db.now()
        run = db.insert_run(
            {
                "source": source,
                "started_at": started,
                "finished_at": finished,
                "processed": len(results),
                "leads": sum(1 for item in results if item.get("lead")),
                "alerts": sum(1 for item in results if item.get("alert")),
                "ingested": ingested,
            }
        )
        return {**run, "results": results}


def start_worker() -> None:
    global _scheduler
    if not worker_enabled() or _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: run_once("scheduler"),
        trigger="interval",
        seconds=interval_seconds(),
        id="lane-intake",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler


def stop_worker() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None


def status() -> dict:
    next_run = None
    running = _scheduler is not None and _scheduler.running
    if _scheduler is not None:
        job = _scheduler.get_job("lane-intake")
        if job is not None and job.next_run_time is not None:
            next_run = job.next_run_time.isoformat()
    return {
        "enabled": running,
        "interval_seconds": interval_seconds(),
        "next_run_at": next_run,
        "last_run": db.latest_run(),
        "engine": "apscheduler",
    }
