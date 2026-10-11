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
from ntk_common.jobs import (
    TASK_BUILD_BRIEFS,
    TASK_BUILD_CLAIM,
    TASK_BUILD_DIGESTS,
    TASK_BUILD_GUIDES,
    TASK_CLASSIFY_INBOX,
    TASK_DELIVER_WEBHOOKS,
    TASK_POLL_BATCHES,
    TASK_RUN_EVALUATION,
    TASK_RUN_JOB,
    TASK_SCAN_INBOX,
    TASK_SUBMIT_DIGEST_BATCH,
    TASK_VERIFY_ARTIFACT,
)
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
        _sync_inbox(p, job_id, job["status"])
        return {"job_id": job_id, "status": job["status"]}
    except StageError as exc:
        if exc.retryable and self.request.retries < MAX_RETRIES:
            with p.s.engine.begin() as conn:
                ops.reset_failed_stages(conn, job_id)
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc
        _dead_letter(TASK_RUN_JOB, job_id, {"job_id": job_id}, exc)
        _sync_inbox(p, job_id, "failed")
        return {"job_id": job_id, "status": "failed"}
    except Exception as exc:  # noqa: BLE001
        log.error("job %s failed: %s: %s", job_id, type(exc).__name__, str(exc)[:300])
        if self.request.retries < MAX_RETRIES:
            with p.s.engine.begin() as conn:
                ops.reset_failed_stages(conn, job_id)
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc
        _dead_letter(TASK_RUN_JOB, job_id, {"job_id": job_id}, exc)
        _sync_inbox(p, job_id, "failed")
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
    """Rebuild and re-gate a hearing digest or claim card after its sources or judicial statements changed."""
    p = _pipeline()
    with p.s.engine.connect() as conn:
        art = kdb.get_artifact(conn, artifact_id)
    if art is None:
        return {"artifact_id": artifact_id, "status": "not_found"}
    # a rebuild creates a new draft version through the same gates; the published version stays until a human re-approves
    if art["object_type"] == "hearing":
        out = p.rebuild_hearing_digest(str(art["object_id"]))
        return {"artifact_id": artifact_id, "status": "rebuilt", "new": out}
    if art["object_type"] == "claim":
        out = p.build_claim(str(art["object_id"]))
        return {"artifact_id": artifact_id, "status": "rebuilt", "new": out}
    return {"artifact_id": artifact_id, "status": "unsupported", "object_type": art["object_type"]}


def _sync_inbox(p: Pipeline, job_id: str, status: str) -> None:
    from ntk_common.inbox import sync_job_status

    try:
        with p.s.engine.begin() as conn:
            sync_job_status(conn, job_id, status)
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not fail the job
        log.warning("inbox status sync failed for job %s: %s", job_id, type(exc).__name__)


class _CeleryJobQueue:
    def enqueue(self, task: str, *args: str) -> str:
        return app.send_task(task, args=list(args), queue="ntk").id


@app.task(name=TASK_SCAN_INBOX)
def scan_inbox(trigger: str = "schedule", process: str = "") -> dict:
    """List the inbox, register new objects, and fan classification out in batches.

    ``process``: "1"/"0" from an operator; empty → NTK_INBOX_AUTO_PROCESS (scheduled runs)."""
    from ntk_common import inbox

    p = _pipeline()
    s = p.cfg
    if trigger == "schedule" and not s.inbox_enabled:
        return {"skipped": "inbox disabled"}
    do_process = s.inbox_auto_process if process == "" else process == "1"
    if p.s.storage is None:
        return {"error": "storage not configured"}
    sid = inbox.start_scan(p.s.engine, trigger=trigger)
    try:
        res = inbox.list_new(p.s, prefix=s.inbox_prefix, scan_id=sid)
    except Exception as exc:  # noqa: BLE001
        inbox.finish_scan(p.s.engine, sid, stats={}, error={"type": type(exc).__name__, "message": str(exc)[:500]})
        raise
    ids_ = res["pending_ids"]
    size = max(1, s.inbox_batch_size)
    for i in range(0, len(ids_), size):
        app.send_task(TASK_CLASSIFY_INBOX, args=[ids_[i:i + size], "1" if do_process else "0"], queue="ntk")
    stats = {"listed": res["listed"], "new": res["new"], "to_classify": len(ids_), "batches": -(-len(ids_) // size),
             "process": do_process, "prefix": s.inbox_prefix}
    inbox.finish_scan(p.s.engine, sid, stats=stats)
    return {"scan_id": sid, **stats}


@app.task(name=TASK_CLASSIFY_INBOX)
def classify_inbox_batch(item_ids: list[str], process: str = "0") -> dict:
    from ntk_common import inbox

    p = _pipeline()
    out: dict[str, int] = {}
    for iid in item_ids:
        st = inbox.classify_item(p.s, iid)
        out[st] = out.get(st, 0) + 1
    if process == "1":
        q = inbox.queue_items(p.s, _CeleryJobQueue(), task_name=TASK_RUN_JOB, item_ids=item_ids, requested_by="inbox:auto")
        out["jobs_created"] = q["jobs_created"]
    return out


@app.task(name=TASK_SUBMIT_DIGEST_BATCH)
def submit_digest_batch(spec: str) -> dict:
    """Send hearing digests through the Batch API (half price). ``spec`` JSON: {"hearing_ids"?, "limit"?}."""
    from ntk_common import batches

    p = _pipeline()
    args = json.loads(spec or "{}")
    try:
        out = batches.submit_digests(p, hearing_ids=args.get("hearing_ids"), limit=int(args.get("limit", 200)))
    except Exception as exc:  # noqa: BLE001 - recorded, not redelivered
        log.error("submit_digest_batch failed: %s: %s", type(exc).__name__, str(exc)[:300])
        out = {"error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
    with p.s.engine.begin() as conn:
        ops.audit(conn, actor="worker", action="batch.submit_requested", object_type="model_batch", object_id="digest",
                  details=json.loads(json.dumps(out, ensure_ascii=False, default=str)))
    return {"ok": "error" not in out}


@app.task(name=TASK_POLL_BATCHES)
def poll_batches() -> dict:
    """Collect finished batches (beat, every 10 minutes); builds and publishes digests under the usual gates."""
    from ntk_common import batches

    p = _pipeline()
    try:
        out = batches.poll(p)
    except Exception as exc:  # noqa: BLE001
        log.error("poll_batches failed: %s: %s", type(exc).__name__, str(exc)[:300])
        return {"error": type(exc).__name__}
    return {"batches": len(out["batches"])}


@app.task(name=TASK_BUILD_DIGESTS)
def build_digests(spec: str) -> dict:
    """Hearing digests built on request (when NTK_HEARING_DIGESTS=deferred). ``spec`` JSON: {"hearing_ids"?,
    "limit"?} — without ids, the oldest published hearings that have no digest yet. Audited as ``digests.built``."""
    from ntk_common.db.core import rows

    p = _pipeline()
    args = json.loads(spec or "{}")
    with p.s.engine.connect() as conn:
        hs = [r["id"] for r in rows(conn, """
            SELECT h.id FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
            WHERE (CAST(:ids AS text[]) IS NULL OR h.id = ANY(:ids))
              AND (CAST(:ids AS text[]) IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM ntk.generated_artifacts ga WHERE ga.object_type = 'hearing' AND ga.object_id = h.id
                      AND ga.review_state IN ('machine_verified', 'human_review_required', 'approved', 'published')))
            ORDER BY h.hearing_date LIMIT :lim""", {"ids": args.get("hearing_ids"), "lim": int(args.get("limit", 20))})]
    results = []
    for hid in hs:
        try:
            results.append({"hearing_id": hid, **p.rebuild_hearing_digest(hid)})
        except Exception as exc:  # noqa: BLE001 - one hearing must not stop the batch
            results.append({"hearing_id": hid, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    with p.s.engine.begin() as conn:
        ops.audit(conn, actor="worker", action="digests.built", object_type="hearing", object_id="batch",
                  details=json.loads(json.dumps({"results": results}, ensure_ascii=False, default=str)))
    return {"hearings": len(hs)}


@app.task(name=TASK_BUILD_BRIEFS)
def build_briefs(spec: str) -> dict:
    """Briefs for non-protocol documents. ``spec`` JSON: {"source_version_ids"?, "only_missing": true}. Audited."""
    from ntk_common.db.core import rows

    p = _pipeline()
    args = json.loads(spec or "{}")
    with p.s.engine.connect() as conn:
        svs = [r["id"] for r in rows(conn, """
            SELECT sv.id FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
            WHERE d.source_type <> 'protocol' AND NOT EXISTS (SELECT 1 FROM ntk.hearings h WHERE h.source_version_id = sv.id)
              AND (CAST(:ids AS text[]) IS NULL OR sv.id = ANY(:ids))
              AND (NOT :only_missing OR NOT EXISTS (
                    SELECT 1 FROM ntk.generated_artifacts ga WHERE ga.object_type = 'document' AND ga.object_id = sv.id
                      AND ga.review_state IN ('machine_verified', 'human_review_required', 'approved', 'published')))
            ORDER BY sv.id""", {"ids": args.get("source_version_ids"), "only_missing": bool(args.get("only_missing", True))})]
    results = []
    for svid in svs:
        try:
            results.append({"source_version_id": svid, **p.build_document_brief(svid)})
        except Exception as exc:  # noqa: BLE001 - one document must not stop the batch
            log.error("brief %s failed: %s: %s", svid, type(exc).__name__, str(exc)[:300])
            results.append({"source_version_id": svid, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    out = {"documents": len(svs), "results": results}
    with p.s.engine.begin() as conn:
        ops.audit(conn, actor="worker", action="briefs.built", object_type="document", object_id="batch",
                  details=json.loads(json.dumps(out, ensure_ascii=False, default=str)))
    return {"documents": len(svs)}


@app.task(name=TASK_BUILD_GUIDES)
def build_guides(spec: str) -> dict:
    """Build reader guides (ADR-0015). ``spec`` is JSON: {"kind", "source_version_id"?, "keys"?}. The result is audited."""
    from ntk_common import guide_service

    p = _pipeline()
    args = json.loads(spec or "{}")
    try:
        out = guide_service.build(p, kind=args.get("kind", "all"), source_version_id=args.get("source_version_id"),
                                  keys=args.get("keys"))
    except Exception as exc:  # noqa: BLE001 - recorded, not redelivered (model calls are expensive)
        log.error("build_guides failed: %s: %s", type(exc).__name__, str(exc)[:300])
        out = {"error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
    with p.s.engine.begin() as conn:
        ops.audit(conn, actor="worker", action="guides.built", object_type="guide", object_id=args.get("kind", "all"),
                  details=json.loads(json.dumps(out, ensure_ascii=False, default=str)))
    return out


@app.task(name=TASK_RUN_EVALUATION)
def run_evaluation(run_id: str) -> dict:
    """Run a search benchmark or an Ask suite against the deployed corpus and models; store the report."""
    p = _pipeline()
    return execute_evaluation(p, run_id)


def execute_evaluation(p: Pipeline, run_id: str) -> dict:
    from ntk_common.evaluation import resolve_suite
    from ntk_common.evaluation import run_evaluation as _run

    with p.s.engine.begin() as conn:
        run = ops.get_eval_run(conn, run_id, with_report=False)
        if run is None:
            return {"run_id": run_id, "status": "not_found"}
        if not ops.start_eval_run(conn, run_id, models=p.s.registry.describe()):
            return {"run_id": run_id, "status": run["status"]}
    try:
        report = _run(run["kind"], resolve_suite(run["suite"]), settings=p.cfg, engine=p.s.engine, services=p.s,
                      options=run["options"] or {})
    except Exception as exc:  # noqa: BLE001 - the error is stored on the run, never re-raised into a redelivery loop
        log.error("evaluation %s failed: %s: %s", run_id, type(exc).__name__, str(exc)[:300])
        with p.s.engine.begin() as conn:
            ops.finish_eval_run(conn, run_id, status="failed", error={"type": type(exc).__name__, "message": str(exc)[:1000]})
        return {"run_id": run_id, "status": "failed"}
    report = json.loads(json.dumps(report, ensure_ascii=False, default=str))
    with p.s.engine.begin() as conn:
        ops.finish_eval_run(conn, run_id, status="succeeded", summary=report.get("summary"), report=report)
    return {"run_id": run_id, "status": "succeeded"}


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
