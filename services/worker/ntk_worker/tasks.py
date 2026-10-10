"""Worker tasks. Secrets never reach logs: errors are logged by type and
message only, and the settings object redacts secrets in repr."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from functools import lru_cache

from ntk_common.config import get_settings
from ntk_common.db import knowledge as kdb
from ntk_common.db import ops
from ntk_common.db.core import get_engine
from ntk_common.jobs import TASK_BUILD_CLAIM, TASK_DELIVER_WEBHOOKS, TASK_RUN_JOB, TASK_VERIFY_ARTIFACT
from ntk_common.orchestrator import Pipeline, StageError, build_services

from .celery_app import app

log = logging.getLogger("ntk.worker")
MAX_RETRIES = 3


@lru_cache(maxsize=1)
def _pipeline() -> Pipeline:
    s = get_settings()
    services = build_services(s, get_engine(s.database_url))
    with services.engine.begin() as conn:
        ops.sync_registry(conn, services.registry.rows())
    return Pipeline(services)


def _dead_letter(task_name: str, job_id: str | None, payload: dict, exc: BaseException) -> None:
    p = _pipeline()
    with p.s.engine.begin() as conn:
        ops.dead_letter(conn, job_id=job_id, task_name=task_name, payload=payload,
                        error={"type": type(exc).__name__, "message": str(exc)[:1000]})


@app.task(name=TASK_RUN_JOB, bind=True, max_retries=MAX_RETRIES)
def run_ingestion_job(self, job_id: str) -> dict:
    p = _pipeline()
    try:
        job = p.run_job(job_id)
        return {"job_id": job_id, "status": job["status"]}
    except StageError as exc:
        if exc.retryable and self.request.retries < MAX_RETRIES:
            with p.s.engine.begin() as conn:
                ops.reset_failed_stages(conn, job_id)
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc
        _dead_letter(TASK_RUN_JOB, job_id, {"job_id": job_id}, exc)
        return {"job_id": job_id, "status": "failed"}
    except Exception as exc:  # noqa: BLE001
        log.error("job %s failed: %s: %s", job_id, type(exc).__name__, str(exc)[:300])
        if self.request.retries < MAX_RETRIES:
            with p.s.engine.begin() as conn:
                ops.reset_failed_stages(conn, job_id)
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc
        _dead_letter(TASK_RUN_JOB, job_id, {"job_id": job_id}, exc)
        return {"job_id": job_id, "status": "failed"}


@app.task(name=TASK_BUILD_CLAIM, bind=True, max_retries=MAX_RETRIES)
def build_claim(self, claim_id: str) -> dict:
    p = _pipeline()
    try:
        return p.build_claim(claim_id)
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc
        _dead_letter(TASK_BUILD_CLAIM, None, {"claim_id": claim_id}, exc)
        raise


@app.task(name=TASK_VERIFY_ARTIFACT)
def verify_artifact(artifact_id: str) -> dict:
    """Re-run gates for a digest after its sources or judicial statements changed."""
    p = _pipeline()
    with p.s.engine.connect() as conn:
        art = kdb.get_artifact(conn, artifact_id)
    if art is None:
        return {"artifact_id": artifact_id, "status": "not_found"}
    if art["object_type"] == "hearing":
        job_like = art["object_id"]
        return {"artifact_id": artifact_id, "status": "rebuild_via_job", "hearing_id": job_like}
    return {"artifact_id": artifact_id, "status": "unsupported"}


@app.task(name=TASK_DELIVER_WEBHOOKS)
def deliver_webhooks() -> dict:
    """POST pending outbox events to WordPress with an HMAC signature."""
    import requests

    s = get_settings()
    if not s.wp_callback_url or not s.wp_callback_secret:
        return {"delivered": 0, "note": "WP_CALLBACK_URL / WP_CALLBACK_SECRET not configured"}
    p = _pipeline()
    delivered = 0
    with p.s.engine.begin() as conn:
        for w in ops.due_webhooks(conn):
            body = json.dumps({"id": str(w["id"]), "event": w["event_type"], "payload": w["payload"]}, ensure_ascii=False)
            ts = str(int(time.time()))
            sig = hmac.new(s.wp_callback_secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
            try:
                r = requests.post(s.wp_callback_url, data=body.encode(), timeout=10,
                                  headers={"Content-Type": "application/json", "X-NTK-Timestamp": ts, "X-NTK-Webhook-Signature": sig})
                ok = 200 <= r.status_code < 300
                ops.mark_webhook(conn, w["id"], delivered=ok, error=None if ok else f"HTTP {r.status_code}")
                delivered += int(ok)
            except Exception as exc:  # noqa: BLE001
                ops.mark_webhook(conn, w["id"], delivered=False, error=type(exc).__name__)
    return {"delivered": delivered}
