"""Admin endpoints (signed service accounts, explicit scopes, audited).

Scopes: admin:read, admin:ingest, admin:review, admin:publish, admin:claims
(admin:all grants everything)."""

from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from ntk_common import ids
from ntk_common import inbox as inboxmod
from ntk_common.db import knowledge as kdb
from ntk_common.db import ops
from ntk_common.db.core import execute, row, rows
from ntk_common.db.public import units_by_ids
from ntk_common.evaluation import SuiteNotFound, resolve_suite
from ntk_common.jobs import (
    TASK_BUILD_CLAIM,
    TASK_BUILD_GUIDES,
    TASK_RUN_EVALUATION,
    TASK_RUN_JOB,
    TASK_SCAN_INBOX,
    TASK_VERIFY_ARTIFACT,
)
from ntk_common.orchestrator import STAGES, doc_input_from_manifest, job_idempotency_key

from ..app import ApiError, AppState
from ..deps import admin, get_state
from ..schemas import (
    CaseEventIn,
    ClaimIn,
    DuplicateDecision,
    EvaluationRequest,
    GuideBuildRequest,
    InboxItemOverride,
    InboxProcessRequest,
    InboxScanRequest,
    IngestionJobRequest,
    ObjectReviewRequest,
    PresignRequest,
    PresignResponse,
    PriorityIn,
    Project315ImportRequest,
    PublishRequest,
    ReviewRequest,
    StageRerunRequest,
    UnpublishRequest,
)
from ..security import Principal
from .public import _json

router = APIRouter(prefix="/v2/admin", tags=["admin"])
STALE_JOB_MINUTES = 15


def _uuid_or_404(v: str) -> None:
    import uuid as _u

    try:
        _u.UUID(v)
    except ValueError as exc:
        raise ApiError(404, "not_found", "unknown id") from exc


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", None) or ""


def _pub_error(exc: kdb.PublicationError) -> ApiError:
    status = {"not_found": 404, "conflict": 409, "review_required": 409, "unpublished_object": 409,
              "citation_gate_failed": 422, "invalid_request": 400}.get(exc.code, 400)
    return ApiError(status, exc.code if exc.code != "not_found" else "not_found", str(exc), exc.details)


# ------------------------------------------------------------------ uploads
@router.post("/uploads/presign", response_model=PresignResponse)
def presign(body: PresignRequest, request: Request, st: AppState = Depends(get_state),
            p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    if body.size_bytes > st.settings.max_upload_bytes:
        raise ApiError(413, "payload_too_large", f"file exceeds {st.settings.max_upload_bytes} bytes")
    storage = st.services.storage
    if storage is None:
        raise ApiError(503, "internal_error", "object storage is not configured")
    key = storage.content_key(body.sha256.lower())
    pre = storage.presign_put(key, mime_type=body.mime_type, size=body.size_bytes, sha256=body.sha256.lower(),
                              ttl=st.settings.presign_ttl_seconds)
    with st.services.engine.begin() as conn:
        up = ops.create_upload(conn, bucket=storage.bucket, key=key, filename=body.filename, mime_type=body.mime_type,
                               size_bytes=body.size_bytes, expected_sha256=body.sha256.lower(), requested_by=p.label,
                               ttl_seconds=st.settings.presign_ttl_seconds,
                               status="uploaded" if pre.already_exists else "pending")
        ops.audit(conn, actor=p.label, action="upload.presign", object_type="upload", object_id=str(up["id"]),
                  request_id=_rid(request), details={"key": key, "size": body.size_bytes, "already_exists": pre.already_exists})
    return _json({"upload_id": str(up["id"]), "method": pre.method, "url": pre.url, "headers": pre.headers,
                  "bucket": pre.bucket, "key": pre.key, "expires_in": pre.expires_in,
                  "already_exists": pre.already_exists}, cache="no-store")


# ------------------------------------------------------------------ ingestion jobs
@router.post("/ingestion-jobs", status_code=202)
def create_ingestion_job(body: IngestionJobRequest, request: Request, st: AppState = Depends(get_state),
                         p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    if not (body.upload_id or body.s3_key or body.url):
        raise ApiError(400, "invalid_request", "one of upload_id, s3_key or url is required")
    if body.stages and any(s not in STAGES for s in body.stages):
        raise ApiError(400, "invalid_request", f"unknown stage; valid: {STAGES}")
    doc = body.document.model_dump(mode="json")
    entry = {**doc, "upload_id": body.upload_id, "s3_key": body.s3_key, "claim_ids": body.claim_ids}
    if body.url:
        entry["url"] = body.url
    inp = doc_input_from_manifest({"name": "api", "case_id": st.settings.case_id,
                                   "court_record_status": doc["court_record_status"]}, entry)
    if body.upload_id:
        with st.services.engine.connect() as conn:
            up = ops.get_upload(conn, body.upload_id)
        if up is None:
            raise ApiError(404, "not_found", "upload not found")
        inp["source"]["expected_sha256"] = up["expected_sha256"]
    key = job_idempotency_key(inp)
    with st.services.engine.begin() as conn:
        job, created = ops.create_job(conn, idempotency_key=key, input_=inp, requested_by=p.label,
                                      upload_id=body.upload_id, stages=body.stages)
        ops.audit(conn, actor=p.label, action="ingestion_job.create", object_type="ingestion_job", object_id=str(job["id"]),
                  request_id=_rid(request), details={"created": created, "document": doc["title"]})
    if created:
        st.queue.enqueue(TASK_RUN_JOB, str(job["id"]))
    return _json({"job_id": str(job["id"]), "created": created, "status": job["status"]}, cache="no-store", status=202)


@router.get("/ingestion-jobs")
def list_jobs(st: AppState = Depends(get_state), status: str | None = None, limit: int = Query(50, le=200),
              p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": ops.list_jobs(conn, limit=limit, status=status)}, cache="no-store")


@router.get("/ingestion-jobs/{job_id}")
def get_job(job_id: str, st: AppState = Depends(get_state), p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        job = ops.get_job(conn, job_id)
    if job is None:
        raise ApiError(404, "not_found", "job not found")
    done = sum(1 for s in job["stages"] if s["status"] in {"succeeded", "skipped"})
    job["progress"] = {"done": done, "total": len(job["stages"])}
    for s in job["stages"]:
        s.pop("checkpoint", None)  # checkpoints can be large and are internal
    return _json(job, cache="no-store")


@router.post("/ingestion-jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request, st: AppState = Depends(get_state),
              p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    with st.services.engine.begin() as conn:
        job = ops.get_job(conn, job_id)
        if job is None:
            raise ApiError(404, "not_found", "job not found")
        if job["status"] in {"running", "queued"}:
            raise ApiError(409, "conflict", f"job is {job['status']}")
        n = ops.reset_failed_stages(conn, job_id)
        ops.audit(conn, actor=p.label, action="ingestion_job.retry", object_type="ingestion_job", object_id=job_id,
                  request_id=_rid(request), details={"stages_reset": n})
    st.queue.enqueue(TASK_RUN_JOB, job_id)
    return _json({"job_id": job_id, "status": "queued", "stages_reset": n}, cache="no-store", status=202)


# ------------------------------------------------------------------ review
@router.post("/ingestion-jobs/{job_id}/rerun", status_code=202)
def rerun_stages(job_id: str, body: StageRerunRequest, request: Request, st: AppState = Depends(get_state),
                 p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    """Re-run the named stages (e.g. embed, extract_a, verify after switching models). Earlier stages keep their results."""
    bad = [s for s in body.stages if s not in STAGES]
    if bad:
        raise ApiError(400, "invalid_request", f"unknown stage {bad}; valid: {STAGES}")
    if "publish" in body.stages:
        raise ApiError(400, "invalid_request", "publish is an explicit admin action, not a pipeline stage to re-run")
    with st.services.engine.begin() as conn:
        job = ops.get_job(conn, job_id)
        if job is None:
            raise ApiError(404, "not_found", "job not found")
        if job["status"] in {"running", "queued"}:
            idle = dt.datetime.now(dt.UTC) - job["updated_at"]
            if not (body.force_stale and idle >= dt.timedelta(minutes=STALE_JOB_MINUTES)):
                raise ApiError(409, "conflict", f"job is {job['status']}"
                               + (f"; force_stale needs {STALE_JOB_MINUTES} idle minutes" if body.force_stale else ""))
        n = ops.reset_stages(conn, job_id, list(dict.fromkeys(body.stages)))
        ops.audit(conn, actor=p.label, action="ingestion_job.rerun", object_type="ingestion_job", object_id=job_id,
                  request_id=_rid(request), details={"stages": body.stages, "stages_reset": n,
                                                     "forced_stale": job["status"] in {"running", "queued"}})
    st.queue.enqueue(TASK_RUN_JOB, job_id)
    return _json({"job_id": job_id, "status": "queued", "stages_reset": n}, cache="no-store", status=202)


# ------------------------------------------------------------------ evaluation runs
@router.post("/guides/build", status_code=202)
def build_guides(body: GuideBuildRequest, request: Request, st: AppState = Depends(get_state),
                 p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    """Build reader guides (ADR-0015) in the worker. Results are audited as ``guides.built``; new guides enter review."""
    spec = body.model_dump(exclude_none=True)
    with st.services.engine.begin() as conn:
        ops.audit(conn, actor=p.label, action="guides.build.requested", object_type="guide", object_id=body.kind,
                  request_id=_rid(request), details=spec)
    tid = st.queue.enqueue(TASK_BUILD_GUIDES, json.dumps(spec))
    return _json({"queued": TASK_BUILD_GUIDES, "task_id": tid, **spec}, cache="no-store", status=202)


@router.post("/evaluations", status_code=202)
def create_evaluation(body: EvaluationRequest, request: Request, st: AppState = Depends(get_state),
                      p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    try:
        path = resolve_suite(body.suite)
    except SuiteNotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    options = {"published_only": body.published_only} if body.kind == "search_bench" else {}
    if body.as_of is not None:
        options["as_of"] = body.as_of.isoformat()
    with st.services.engine.begin() as conn:
        run = ops.create_eval_run(conn, kind=body.kind, suite=path.stem, options=options, requested_by=p.label)
        ops.audit(conn, actor=p.label, action="evaluation.create", object_type="evaluation_run", object_id=str(run["id"]),
                  request_id=_rid(request), details={"kind": body.kind, "suite": path.stem, **options})
    st.queue.enqueue(TASK_RUN_EVALUATION, str(run["id"]))
    return _json({"run_id": str(run["id"]), "status": run["status"], "kind": body.kind, "suite": path.stem},
                 cache="no-store", status=202)


@router.get("/evaluations")
def list_evaluations(st: AppState = Depends(get_state), limit: int = Query(50, le=200),
                     p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": ops.list_eval_runs(conn, limit=limit)}, cache="no-store")


@router.get("/evaluations/{run_id}")
def get_evaluation(run_id: str, st: AppState = Depends(get_state), report: bool = True,
                   p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    try:
        import uuid

        uuid.UUID(run_id)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "run_id must be a UUID") from exc
    with st.services.engine.connect() as conn:
        run = ops.get_eval_run(conn, run_id, with_report=report)
    if run is None:
        raise ApiError(404, "not_found", "evaluation run not found")
    return _json(run, cache="no-store")


# ------------------------------------------------------------------ object-store inbox
@router.post("/inbox/scan", status_code=202)
def inbox_scan(body: InboxScanRequest, request: Request, st: AppState = Depends(get_state),
               p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    flag = "" if body.process is None else ("1" if body.process else "0")
    with st.services.engine.begin() as conn:
        ops.audit(conn, actor=p.label, action="inbox.scan", object_type="inbox", object_id=st.settings.inbox_prefix,
                  request_id=_rid(request), details={"process": body.process})
    tid = st.queue.enqueue(TASK_SCAN_INBOX, "manual", flag)
    return _json({"status": "queued", "task_id": tid, "prefix": st.settings.inbox_prefix,
                  "process": body.process if body.process is not None else st.settings.inbox_auto_process},
                 cache="no-store", status=202)


@router.get("/inbox")
def inbox_status(st: AppState = Depends(get_state), status: str | None = None, kind: str | None = None,
                 limit: int = Query(100, le=5000), offset: int = Query(0, ge=0),
                 p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        summ = inboxmod.summary(conn)
        items = rows(conn, """SELECT id, object_key, size_bytes, status, doc_kind, content_sha256, duplicate_of, job_id,
                                     classification, error, first_seen_at, updated_at
                              FROM ntk.inbox_items
                              WHERE (CAST(:st AS text) IS NULL OR status = :st) AND (CAST(:k AS text) IS NULL OR doc_kind = :k)
                              ORDER BY object_key LIMIT :lim OFFSET :off""",
                     {"st": status, "k": kind, "lim": limit, "off": offset})
    return _json({"prefix": st.settings.inbox_prefix, "auto_process": st.settings.inbox_auto_process,
                  "summary": summ, "items": items}, cache="no-store")


@router.post("/inbox/process", status_code=202)
def inbox_process(body: InboxProcessRequest, request: Request, st: AppState = Depends(get_state),
                  p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    res = inboxmod.queue_items(st.services, st.queue, task_name=TASK_RUN_JOB, kinds=body.kinds, limit=body.limit,
                               item_ids=body.item_ids, requested_by=p.label)
    with st.services.engine.begin() as conn:
        ops.audit(conn, actor=p.label, action="inbox.process", object_type="inbox", object_id=st.settings.inbox_prefix,
                  request_id=_rid(request), details={"kinds": body.kinds, "limit": body.limit, **res})
    return _json(res, cache="no-store", status=202)


@router.get("/inbox/duplicates")
def inbox_duplicates(st: AppState = Depends(get_state), limit: int = Query(200, le=1000),
                     p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    """Exact duplicates removed from inbox/, exact duplicates still there, and held possible duplicates."""
    from ntk_common import inbox_dupes

    with st.services.engine.connect() as conn:
        out = inbox_dupes.listing(conn, limit=limit)
    return _json({**out, "auto_delete": st.settings.inbox_delete_duplicates,
                  "threshold": inbox_dupes.POSSIBLE_THRESHOLD}, cache="no-store")


@router.post("/inbox/items/{item_id}/duplicate")
def inbox_duplicate_decision(item_id: str, body: DuplicateDecision, request: Request, st: AppState = Depends(get_state),
                             p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    from ntk_common import inbox_dupes

    _uuid_or_404(item_id)
    if body.action == "remove_copy":
        res = inbox_dupes.remove_copy(st.services, item_id, actor=p.label, reason="operator: duplicate copy")
        if not res.get("removed"):
            raise ApiError(409, "conflict", f"not removed: {res.get('reason')}")
        return _json(res, cache="no-store")
    res = inbox_dupes.release(st.services, item_id, actor=p.label)
    if not res.get("released"):
        raise ApiError(409, "conflict", res.get("reason", "not released"))
    if st.settings.inbox_auto_process and res["status"] == "classified":
        res["queue"] = inboxmod.queue_items(st.services, st.queue, task_name=TASK_RUN_JOB, item_ids=[item_id],
                                            requested_by=p.label)
    return _json(res, cache="no-store")


@router.post("/inbox/items/{item_id}")
def inbox_override(item_id: str, body: InboxItemOverride, request: Request, st: AppState = Depends(get_state),
                   p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    try:
        import uuid

        uuid.UUID(item_id)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "item_id must be a UUID") from exc
    with st.services.engine.begin() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": item_id})
        if it is None:
            raise ApiError(404, "not_found", "inbox item not found")
        if it["status"] in {"queued", "ingested"}:
            raise ApiError(409, "conflict", f"item is already {it['status']}")
        if it["status"] in {"discovered", "unsupported", "failed"} and not body.skip:
            raise ApiError(409, "conflict", f"item is {it['status']}; only skip is possible")
        c = dict(it["classification"] or {})
        if body.skip:
            new_status, kind = "skipped", it["doc_kind"]
        else:
            kind = body.source_type or it["doc_kind"]
            for k in ("hearing_date", "document_date"):
                if getattr(body, k) is not None:
                    c[k] = getattr(body, k).isoformat()
            if body.title:
                c["title"] = body.title
            if body.case_number_verified is not None:
                c["case_found"] = body.case_number_verified
            c.update({"source_type": kind, "method": "manual", "confidence": 1.0, "reviewed_by": p.label})
            new_status = "foreign_case" if c.get("case_found") is False else "classified"
        execute(conn, """UPDATE ntk.inbox_items SET status = :s, doc_kind = :k, classification = CAST(:c AS jsonb),
                         updated_at = now() WHERE id = CAST(:id AS uuid)""",
                {"s": new_status, "k": kind, "c": json.dumps(c, ensure_ascii=False, default=str), "id": item_id})
        ops.audit(conn, actor=p.label, action="inbox.override", object_type="inbox_item", object_id=item_id,
                  request_id=_rid(request), details=body.model_dump(mode="json"))
    return _json({"id": item_id, "status": new_status, "doc_kind": kind}, cache="no-store")


@router.get("/review-tasks")
def review_tasks(st: AppState = Depends(get_state), status: str = "open", p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": kdb.list_review_tasks(conn, status=status)}, cache="no-store")


@router.get("/artifacts")
def list_artifacts(st: AppState = Depends(get_state), state: str | None = None, artifact_type: str | None = None,
                   p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": kdb.list_artifacts(conn, state=state, artifact_type=artifact_type)}, cache="no-store")


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, st: AppState = Depends(get_state), p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    """Everything the review screen shows side by side: writer output,
    verifier output, gate report, model/prompt provenance and the cited
    source text."""
    with st.services.engine.connect() as conn:
        art = kdb.get_artifact(conn, artifact_id)
        if art is None:
            raise ApiError(404, "not_found", "artifact not found")
        run_ids = [str(x) for x in (art["model_run_id"], art["verifier_run_id"]) if x]
        runs = rows(conn, """SELECT id, task_type, role, provider, model_family, model_version, prompt_version, schema_version,
                                    corpus_version, status, validation_errors, usage, duration_ms, created_at,
                                    CASE WHEN task_type = 'verify' THEN output END AS verifier_output
                             FROM ntk.model_runs WHERE id = ANY(CAST(:ids AS uuid[]))""", {"ids": run_ids})
        cited = [r["source_unit_id"] for r in rows(conn, "SELECT DISTINCT source_unit_id FROM ntk.artifact_citations WHERE artifact_id = CAST(:a AS uuid)",
                                                   {"a": artifact_id})]
        units = units_by_ids(conn, cited, published_only=False)
        tasks = rows(conn, "SELECT * FROM ntk.review_tasks WHERE object_type='artifact' AND object_id=:a ORDER BY created_at",
                     {"a": artifact_id})
        history = ops.list_audit(conn, object_type="artifact", object_id=artifact_id)
    verifier = next((r.get("verifier_output") for r in runs if r["task_type"] == "verify"), None)
    return _json({
        "artifact": {k: art[k] for k in ("id", "artifact_type", "object_type", "object_id", "review_state", "risk_flags",
                                         "created_at", "supersedes_id", "schema_version")},
        "writer_output": art["payload"], "verifier_output": verifier, "gate_report": art["gate_report"],
        "model_runs": [{k: v for k, v in r.items() if k != "verifier_output"} for r in runs],
        "sources": [{"source_unit_id": u.id, "page": u.page, "line_start": u.line_start, "line_end": u.line_end,
                     "speaker": u.speaker_label, "speaker_role": u.speaker_role, "unit_type": u.unit_type, "text": u.text,
                     "published": u.published, "judicial_level": u.judicial_level} for u in units.values()],
        "review_tasks": tasks, "audit": history,
    }, cache="no-store")


@router.post("/artifacts/{artifact_id}/verify", status_code=202)
def verify_artifact(artifact_id: str, request: Request, st: AppState = Depends(get_state),
                    p: Principal = Depends(admin("admin:review"))) -> JSONResponse:
    with st.services.engine.begin() as conn:
        art = kdb.get_artifact(conn, artifact_id)
        if art is None:
            raise ApiError(404, "not_found", "artifact not found")
        ops.audit(conn, actor=p.label, action="artifact.verify.requested", object_type="artifact", object_id=artifact_id,
                  request_id=_rid(request))
    task = TASK_BUILD_CLAIM if art["artifact_type"] == "claim_card" else TASK_VERIFY_ARTIFACT
    arg = art["object_id"] if art["artifact_type"] == "claim_card" else artifact_id
    tid = st.queue.enqueue(task, arg)
    return _json({"artifact_id": artifact_id, "queued": task, "task_id": tid}, cache="no-store", status=202)


@router.post("/artifacts/{artifact_id}/review")
def review_artifact(artifact_id: str, body: ReviewRequest, request: Request, st: AppState = Depends(get_state),
                    p: Principal = Depends(admin("admin:review"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            res = kdb.review_artifact(conn, artifact_id=artifact_id, decision=body.decision, reviewer=p.label,
                                      notes=body.notes, request_id=_rid(request))
            # under NTK_AUTO_PUBLISH=gates a person's approval is the last step: publish right away (sources must be public)
            if body.decision == "approve" and st.settings.auto_publish == "gates" and p.has("admin:publish"):
                try:
                    with conn.begin_nested():
                        pub_res = kdb.publish_artifact(conn, artifact_id=artifact_id, actor=p.label, env=st.settings.env,
                                                       public_base_url=st.settings.public_base_url, include_sources=False,
                                                       request_id=_rid(request))
                    res = {**res, "review_state": pub_res["review_state"], "published_on_approval": True}
                except kdb.PublicationError as exc:
                    res = {**res, "published_on_approval": False, "publish_blocked": str(exc)}
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json(res, cache="no-store")


@router.post("/artifacts/{artifact_id}/publish")
def publish_artifact(artifact_id: str, body: PublishRequest, request: Request, st: AppState = Depends(get_state),
                     p: Principal = Depends(admin("admin:publish"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            res = kdb.publish_artifact(conn, artifact_id=artifact_id, actor=p.label, env=st.settings.env,
                                       public_base_url=st.settings.public_base_url, include_sources=body.include_sources,
                                       request_id=_rid(request))
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json(res, cache="no-store")


@router.post("/artifacts/{artifact_id}/unpublish")
def unpublish_artifact(artifact_id: str, body: UnpublishRequest, request: Request, st: AppState = Depends(get_state),
                       p: Principal = Depends(admin("admin:publish"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            res = kdb.unpublish_artifact(conn, artifact_id=artifact_id, actor=p.label, reason=body.reason,
                                         request_id=_rid(request))
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json(res, cache="no-store")


@router.post("/objects/{object_type}/{object_id}/review")
def review_object(object_type: str, object_id: str, body: ObjectReviewRequest, request: Request,
                  st: AppState = Depends(get_state), p: Principal = Depends(admin("admin:review"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            res = kdb.review_object(conn, object_type=object_type, object_id=object_id, decision=body.decision,
                                    reviewer=p.label, notes=body.notes, request_id=_rid(request))
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json(res, cache="no-store")


# ------------------------------------------------------------------ sources
@router.post("/sources/{source_version_id}/publish")
def publish_source(source_version_id: str, request: Request, st: AppState = Depends(get_state),
                   p: Principal = Depends(admin("admin:publish"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            cv = kdb.publish_source_version(conn, source_version_id, actor=p.label, request_id=_rid(request))
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json({"source_version_id": source_version_id, "publication_state": "published", "corpus_version": cv}, cache="no-store")


@router.post("/sources/{source_version_id}/withdraw")
def withdraw_source(source_version_id: str, body: UnpublishRequest, request: Request, st: AppState = Depends(get_state),
                    p: Principal = Depends(admin("admin:publish"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            cv = kdb.withdraw_source_version(conn, source_version_id, actor=p.label, reason=body.reason, request_id=_rid(request))
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json({"source_version_id": source_version_id, "publication_state": "withdrawn", "corpus_version": cv}, cache="no-store")


# ------------------------------------------------------------------ claims
@router.get("/claims")
def admin_claims(st: AppState = Depends(get_state), p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": kdb.list_claims(conn)}, cache="no-store")


@router.post("/claims", status_code=201)
def create_claim(body: ClaimIn, request: Request, st: AppState = Depends(get_state),
                 p: Principal = Depends(admin("admin:claims"))) -> JSONResponse:
    with st.services.engine.begin() as conn:
        cid, vid = kdb.ensure_claim(conn, case_id=st.settings.case_id, slug=body.slug, question=body.question,
                                    claim_type=body.claim_type, stance=body.stance, title=body.title,
                                    claim_text=body.claim_text, editorial_priority=body.editorial_priority,
                                    thesis_code=body.thesis_code, sensitivity=body.sensitivity, disclosure=body.disclosure,
                                    created_by=p.label)
        ops.audit(conn, actor=p.label, action="claim.upsert", object_type="claim", object_id=cid,
                  request_id=_rid(request), details={"version_id": vid, "slug": body.slug})
    return _json({"claim_id": cid, "version_id": vid}, cache="no-store", status=201)


@router.post("/claims/{claim_id}/rebuild", status_code=202)
def rebuild_claim(claim_id: str, request: Request, st: AppState = Depends(get_state),
                  p: Principal = Depends(admin("admin:claims"))) -> JSONResponse:
    with st.services.engine.begin() as conn:
        if kdb.get_claim(conn, claim_id) is None:
            raise ApiError(404, "not_found", "claim not found")
        ops.audit(conn, actor=p.label, action="claim.rebuild.requested", object_type="claim", object_id=claim_id,
                  request_id=_rid(request))
    tid = st.queue.enqueue(TASK_BUILD_CLAIM, claim_id)
    return _json({"claim_id": claim_id, "task_id": tid}, cache="no-store", status=202)


@router.patch("/claims/{claim_id}/priority")
def set_priority(claim_id: str, body: PriorityIn, request: Request, st: AppState = Depends(get_state),
                 p: Principal = Depends(admin("admin:claims"))) -> JSONResponse:
    try:
        with st.services.engine.begin() as conn:
            vid = kdb.set_editorial_priority(conn, claim_id, body.editorial_priority, p.label)
            ops.audit(conn, actor=p.label, action="claim.priority", object_type="claim", object_id=claim_id,
                      request_id=_rid(request), details={"editorial_priority": body.editorial_priority})
    except kdb.PublicationError as exc:
        raise _pub_error(exc) from exc
    return _json({"claim_id": claim_id, "version_id": vid}, cache="no-store")


# ------------------------------------------------------------------ case events (status / outcomes)
@router.post("/case-events", status_code=201)
def add_case_event(body: CaseEventIn, request: Request, st: AppState = Depends(get_state),
                   p: Principal = Depends(admin("admin:publish"))) -> JSONResponse:
    if body.event_type == "outcome" and not body.outcome:
        raise ApiError(400, "invalid_request", "outcome events need an outcome value")
    if body.event_type == "pardon_requested" and body.outcome:
        raise ApiError(400, "invalid_request", "a pardon request is a process event, not an outcome (spec §23.9)")
    with st.services.engine.begin() as conn:
        eid = kdb.add_case_event(conn, case_id=st.settings.case_id, event_type=body.event_type,
                                 occurred_at=body.occurred_at.isoformat(), title=body.title, description=body.description,
                                 outcome=body.outcome, source_unit_ids=body.source_unit_ids,
                                 external_sources=body.external_sources,
                                 review_state="published" if body.publish else "draft", actor=p.label)
        cv = ops.bump_corpus_version(conn, reason=f"case event {eid}", actor=p.label) if body.publish else None
        ops.audit(conn, actor=p.label, action="case_event.create", object_type="case_event", object_id=eid,
                  request_id=_rid(request), details={"published": body.publish, "type": body.event_type})
        if body.publish:
            ops.enqueue_webhook(conn, "case_event.published", {"case_event_id": eid, "corpus_version": cv})
    return _json({"case_event_id": eid, "corpus_version": cv}, cache="no-store", status=201)


# ------------------------------------------------------------------ Project 315
@router.post("/project315/import")
def import_p315(body: Project315ImportRequest, request: Request, st: AppState = Depends(get_state),
                p: Principal = Depends(admin("admin:ingest"))) -> JSONResponse:
    from ntk_p315.importer import ImportFailed, import_export

    try:
        with st.services.engine.begin() as conn:
            report = import_export(conn, content=body.content, fmt=body.format, source=body.source,
                                   synthetic=body.synthetic, actor=p.label)
            ops.audit(conn, actor=p.label, action="project315.import", object_type="project315_import",
                      object_id=report["run_id"], request_id=_rid(request),
                      details={k: report[k] for k in ("imported", "unchanged", "updated", "warnings_count")})
    except ImportFailed as exc:
        raise ApiError(422, "invalid_request", str(exc), exc.errors) from exc
    return _json(report, cache="no-store")


# ------------------------------------------------------------------ misc
@router.get("/registry")
def registry(st: AppState = Depends(get_state), p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    return _json(st.services.registry.describe(), cache="no-store")


@router.get("/audit")
def audit_log(st: AppState = Depends(get_state), object_type: str | None = None, object_id: str | None = None,
              p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": ops.list_audit(conn, object_type=object_type, object_id=object_id)}, cache="no-store")


@router.get("/whoami")
def whoami(p: Principal = Depends(admin("admin:read"))) -> JSONResponse:
    return _json({"key_id": p.key_id, "actor": p.actor, "scopes": sorted(p.scopes),
                  "server_time": dt.datetime.now(dt.UTC).isoformat()}, cache="no-store")


_ = (ids, row)
