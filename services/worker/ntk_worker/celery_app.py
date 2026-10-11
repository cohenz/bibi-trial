"""Celery application (private worker; no public domain on Railway).

Reliability:
* acks_late + reject_on_worker_lost: a task killed mid-run is redelivered;
* bounded retries with exponential backoff for retryable failures; after the
  last attempt the job is marked failed and a row is written to
  ntk.dead_letters (the DLQ) for inspection and manual retry;
* stage checkpoints make redelivery safe (completed stages are skipped).
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab
from ntk_common.config import get_settings

settings = get_settings()

app = Celery("ntk-worker", broker=settings.redis_url, backend=None, include=["ntk_worker.tasks"])
_schedule = {"deliver-webhooks": {"task": "ntk.deliver_webhooks", "schedule": 30.0}}
if settings.inbox_enabled:
    # daily look for new documents in the object-store inbox (classify; ingest when NTK_INBOX_AUTO_PROCESS)
    _schedule["inbox-daily"] = {"task": "ntk.scan_inbox", "args": ("schedule",),
                                "schedule": crontab(hour=settings.inbox_scan_hour_utc, minute=settings.inbox_scan_minute)}
app.conf.update(
    task_default_queue="ntk",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_time_limit=60 * 60,
    task_soft_time_limit=55 * 60,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 2 * 60 * 60},
    beat_schedule=_schedule,
    timezone="UTC",
)

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
