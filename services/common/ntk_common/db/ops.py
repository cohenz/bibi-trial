"""Operational persistence: ingestion jobs and stage checkpoints, uploads,
audit events, webhook outbox, dead letters, model runs, model registry,
corpus versions."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from .. import ids
from ..llm.runner import ModelRunRecord
from .core import execute, j, row, rows, scalar

PROTOCOL_STAGES = [
    "register", "download", "validate", "extract_text", "ocr_fallback", "lineize", "segment", "pair", "chunk",
    "embed", "extract_a", "map_b", "verify", "review", "publish",
]


# ------------------------------------------------------------------ jobs
def create_job(conn: Connection, *, idempotency_key: str, input_: dict, requested_by: str,
               document_id: str | None = None, upload_id: str | None = None, stages: list[str] | None = None,
               parser_version: str | None = None, prompt_version: str | None = None) -> tuple[dict, bool]:
    """Create or return the job for ``idempotency_key``. Returns (job, created)."""
    existing = row(conn, "SELECT * FROM ntk.ingestion_jobs WHERE idempotency_key = :k", {"k": idempotency_key})
    if existing:
        return existing, False
    stages = stages or PROTOCOL_STAGES
    jid = str(ids.derived_uuid("ingestion_job", idempotency_key))
    execute(conn, """
        INSERT INTO ntk.ingestion_jobs (id, idempotency_key, stage, status, input, requested_by, document_id, upload_id,
            target_stages, parser_version, prompt_version)
        VALUES (:id, :k, :stage, 'queued', CAST(:inp AS jsonb), :by, :doc, CAST(:up AS uuid), :stages, :pv, :prv)
        ON CONFLICT (idempotency_key) DO NOTHING
    """, {"id": jid, "k": idempotency_key, "stage": stages[0], "inp": j(input_), "by": requested_by, "doc": document_id,
          "up": upload_id, "stages": stages, "pv": parser_version, "prv": prompt_version})
    execute(conn, """
        INSERT INTO ntk.ingestion_job_stages (job_id, stage, seq) VALUES (:id, :s, :i) ON CONFLICT DO NOTHING
    """, [{"id": jid, "s": s, "i": i} for i, s in enumerate(stages)])
    return get_job(conn, jid), True  # type: ignore[return-value]


def get_job(conn: Connection, job_id: str) -> dict | None:
    job = row(conn, "SELECT * FROM ntk.ingestion_jobs WHERE id = CAST(:id AS uuid)", {"id": job_id})
    if job is None:
        return None
    job["stages"] = rows(conn, "SELECT * FROM ntk.ingestion_job_stages WHERE job_id = CAST(:id AS uuid) ORDER BY seq",
                         {"id": job_id})
    return job


def list_jobs(conn: Connection, *, limit: int = 50, status: str | None = None) -> list[dict]:
    return rows(conn, """
        SELECT * FROM ntk.ingestion_jobs WHERE (CAST(:st AS text) IS NULL OR status = :st)
        ORDER BY created_at DESC LIMIT :lim
    """, {"st": status, "lim": limit})


def stage_state(conn: Connection, job_id: str, stage: str) -> dict | None:
    return row(conn, "SELECT * FROM ntk.ingestion_job_stages WHERE job_id = CAST(:id AS uuid) AND stage = :s",
               {"id": job_id, "s": stage})


def start_stage(conn: Connection, job_id: str, stage: str) -> None:
    execute(conn, """
        UPDATE ntk.ingestion_job_stages SET status = 'running', attempts = attempts + 1, started_at = now(), error = NULL
        WHERE job_id = CAST(:id AS uuid) AND stage = :s
    """, {"id": job_id, "s": stage})
    execute(conn, """
        UPDATE ntk.ingestion_jobs SET stage = :s, status = 'running', started_at = coalesce(started_at, now()),
            updated_at = now() WHERE id = CAST(:id AS uuid)
    """, {"id": job_id, "s": stage})


def finish_stage(conn: Connection, job_id: str, stage: str, *, status: str, output: dict | None = None,
                 checkpoint: dict | None = None, error: dict | None = None) -> None:
    execute(conn, """
        UPDATE ntk.ingestion_job_stages SET status = :st, output = CAST(:out AS jsonb), checkpoint = CAST(:cp AS jsonb),
            error = CAST(:err AS jsonb), finished_at = now()
        WHERE job_id = CAST(:id AS uuid) AND stage = :s
    """, {"id": job_id, "s": stage, "st": status, "out": j(output) if output is not None else None,
          "cp": j(checkpoint) if checkpoint is not None else None, "err": j(error) if error is not None else None})


def finish_job(conn: Connection, job_id: str, *, status: str, output: dict | None = None, error: dict | None = None,
               source_version_id: str | None = None) -> None:
    execute(conn, """
        UPDATE ntk.ingestion_jobs SET status = :st, output = coalesce(CAST(:out AS jsonb), output),
            error = CAST(:err AS jsonb), finished_at = now(), updated_at = now(),
            source_version_id = coalesce(:sv, source_version_id)
        WHERE id = CAST(:id AS uuid)
    """, {"id": job_id, "st": status, "out": j(output) if output is not None else None,
          "err": j(error) if error is not None else None, "sv": source_version_id})


def set_job_source_version(conn: Connection, job_id: str, source_version_id: str, document_id: str | None = None) -> None:
    execute(conn, """UPDATE ntk.ingestion_jobs SET source_version_id = :sv, document_id = coalesce(:doc, document_id),
                     updated_at = now() WHERE id = CAST(:id AS uuid)""",
            {"id": job_id, "sv": source_version_id, "doc": document_id})


def reset_failed_stages(conn: Connection, job_id: str) -> int:
    """Retry: failed/pending/running stages go back to pending; succeeded stages keep their checkpoints."""
    n = execute(conn, """UPDATE ntk.ingestion_job_stages SET status = 'pending', error = NULL
                         WHERE job_id = CAST(:id AS uuid) AND status IN ('failed','running')""", {"id": job_id})
    execute(conn, """UPDATE ntk.ingestion_jobs SET status = 'queued', error = NULL, dead_lettered = false,
                     attempts = attempts + 1, updated_at = now() WHERE id = CAST(:id AS uuid)""", {"id": job_id})
    return n


def reset_stages(conn: Connection, job_id: str, stages: list[str]) -> int:
    """Re-run: put the named stages back to pending (checkpoints kept), leave every other stage as it is.

    Used after a model or embedding change, when earlier deterministic stages are still valid but the
    model-dependent ones (embed, extract_a, verify, ...) must run again."""
    n = execute(conn, """UPDATE ntk.ingestion_job_stages SET status = 'pending', error = NULL
                         WHERE job_id = CAST(:id AS uuid) AND stage = ANY(:st)""", {"id": job_id, "st": stages})
    execute(conn, """UPDATE ntk.ingestion_jobs SET status = 'queued', error = NULL, dead_lettered = false,
                     attempts = attempts + 1, updated_at = now() WHERE id = CAST(:id AS uuid)""", {"id": job_id})
    return n


# ------------------------------------------------------------------ evaluation runs
EVAL_KINDS = ("search_bench", "ask_suite")


def create_eval_run(conn: Connection, *, kind: str, suite: str, options: dict, requested_by: str) -> dict:
    return row(conn, """INSERT INTO ntk.evaluation_runs (kind, suite, options, requested_by)
                        VALUES (:k, :s, CAST(:o AS jsonb), :by) RETURNING *""",
               {"k": kind, "s": suite, "o": j(options), "by": requested_by})  # type: ignore[return-value]


def get_eval_run(conn: Connection, run_id: str, *, with_report: bool = True) -> dict | None:
    cols = "*" if with_report else "id, kind, suite, options, status, models, summary, error, requested_by, created_at, started_at, finished_at"
    return row(conn, f"SELECT {cols} FROM ntk.evaluation_runs WHERE id = CAST(:id AS uuid)", {"id": run_id})


def list_eval_runs(conn: Connection, *, limit: int = 50) -> list[dict]:
    return rows(conn, """SELECT id, kind, suite, options, status, models, summary, error, requested_by, created_at,
                                started_at, finished_at
                         FROM ntk.evaluation_runs ORDER BY created_at DESC LIMIT :lim""", {"lim": limit})


def start_eval_run(conn: Connection, run_id: str, *, models: dict) -> bool:
    """Mark a queued run as running. False if it already finished (a redelivered task must not overwrite a report)."""
    n = execute(conn, """UPDATE ntk.evaluation_runs SET status = 'running', started_at = now(), models = CAST(:m AS jsonb)
                         WHERE id = CAST(:id AS uuid) AND status IN ('queued', 'running')""", {"id": run_id, "m": j(models)})
    return bool(n)


def finish_eval_run(conn: Connection, run_id: str, *, status: str, summary: dict | None = None, report: dict | None = None,
                    error: dict | None = None) -> None:
    execute(conn, """UPDATE ntk.evaluation_runs SET status = :st, summary = CAST(:s AS jsonb), report = CAST(:r AS jsonb),
                            error = CAST(:e AS jsonb), finished_at = now()
                     WHERE id = CAST(:id AS uuid) AND status = 'running'""",
            {"id": run_id, "st": status, "s": j(summary) if summary is not None else None,
             "r": j(report) if report is not None else None, "e": j(error) if error is not None else None})


def dead_letter(conn: Connection, *, job_id: str | None, task_name: str, payload: dict, error: dict) -> None:
    execute(conn, """INSERT INTO ntk.dead_letters (job_id, task_name, payload, error)
                     VALUES (CAST(:j AS uuid), :t, CAST(:p AS jsonb), CAST(:e AS jsonb))""",
            {"j": job_id, "t": task_name, "p": j(payload), "e": j(error)})
    if job_id:
        execute(conn, "UPDATE ntk.ingestion_jobs SET dead_lettered = true WHERE id = CAST(:id AS uuid)", {"id": job_id})


# ------------------------------------------------------------------ uploads
def create_upload(conn: Connection, *, bucket: str, key: str, filename: str, mime_type: str, size_bytes: int,
                  expected_sha256: str, requested_by: str, ttl_seconds: int, status: str = "pending") -> dict:
    uid = str(ids.derived_uuid("upload", bucket, key))
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ttl_seconds)
    execute(conn, """
        INSERT INTO ntk.uploads (id, s3_bucket, s3_key, filename, mime_type, size_bytes, expected_sha256, requested_by,
            expires_at, status)
        VALUES (:id, :b, :k, :f, :m, :s, :sha, :by, :exp, :st)
        ON CONFLICT (s3_key) DO UPDATE SET expires_at = EXCLUDED.expires_at, filename = EXCLUDED.filename
    """, {"id": uid, "b": bucket, "k": key, "f": filename, "m": mime_type, "s": size_bytes, "sha": expected_sha256,
          "by": requested_by, "exp": expires, "st": status})
    return row(conn, "SELECT * FROM ntk.uploads WHERE s3_key = :k", {"k": key})  # type: ignore[return-value]


def get_upload(conn: Connection, upload_id: str) -> dict | None:
    return row(conn, "SELECT * FROM ntk.uploads WHERE id = CAST(:id AS uuid)", {"id": upload_id})


def set_upload_status(conn: Connection, upload_id: str, status: str) -> None:
    execute(conn, "UPDATE ntk.uploads SET status = :s WHERE id = CAST(:id AS uuid)", {"id": upload_id, "s": status})


# ------------------------------------------------------------------ audit / outbox
def audit(conn: Connection, *, actor: str, action: str, object_type: str, object_id: str | None,
          request_id: str | None = None, ip_hash: str | None = None, details: dict | None = None) -> None:
    execute(conn, """
        INSERT INTO ntk.audit_events (actor, action, object_type, object_id, request_id, ip_hash, details)
        VALUES (:a, :ac, :ot, :oid, :rid, :ip, CAST(:d AS jsonb))
    """, {"a": actor, "ac": action, "ot": object_type, "oid": object_id, "rid": request_id, "ip": ip_hash,
          "d": j(details or {})})


def list_audit(conn: Connection, *, object_type: str | None = None, object_id: str | None = None, limit: int = 100) -> list[dict]:
    return rows(conn, """
        SELECT * FROM ntk.audit_events
        WHERE (CAST(:ot AS text) IS NULL OR object_type = :ot) AND (CAST(:oid AS text) IS NULL OR object_id = :oid)
        ORDER BY occurred_at DESC LIMIT :lim
    """, {"ot": object_type, "oid": object_id, "lim": limit})


def enqueue_webhook(conn: Connection, event_type: str, payload: dict) -> None:
    execute(conn, "INSERT INTO ntk.webhook_outbox (event_type, payload) VALUES (:e, CAST(:p AS jsonb))",
            {"e": event_type, "p": j(payload)})


def due_webhooks(conn: Connection, limit: int = 20) -> list[dict]:
    return rows(conn, """
        SELECT * FROM ntk.webhook_outbox WHERE status = 'pending' AND next_attempt_at <= now()
        ORDER BY created_at LIMIT :lim FOR UPDATE SKIP LOCKED
    """, {"lim": limit})


def mark_webhook(conn: Connection, wid: Any, *, delivered: bool, error: str | None = None, max_attempts: int = 8) -> None:
    if delivered:
        execute(conn, "UPDATE ntk.webhook_outbox SET status='delivered', delivered_at=now(), attempts=attempts+1 WHERE id=:id",
                {"id": wid})
    else:
        execute(conn, """
            UPDATE ntk.webhook_outbox SET attempts = attempts + 1, last_error = :e,
              status = CASE WHEN attempts + 1 >= :max THEN 'failed' ELSE 'pending' END,
              next_attempt_at = now() + make_interval(secs => least(3600, 30 * power(2, attempts)))
            WHERE id = :id
        """, {"id": wid, "e": (error or "")[:500], "max": max_attempts})


# ------------------------------------------------------------------ model runs / registry
class PgRunStore:
    """RunStore backed by ntk.model_runs (cache + record of every model call)."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def get_run(self, run_id: str) -> ModelRunRecord | None:
        with self.engine.connect() as conn:
            r = row(conn, "SELECT * FROM ntk.model_runs WHERE id = CAST(:id AS uuid)", {"id": run_id})
        if r is None:
            return None
        return ModelRunRecord(
            id=str(r["id"]), task_type=r["task_type"], role=r["role"] or "", provider=r["provider"],
            model_family=r["model_family"], model_id=(r["registry_id"] or "::").split(":")[-1] or r["model_version"],
            model_version=r["model_version"], prompt_version=r["prompt_version"], schema_version=r["schema_version"],
            corpus_version=r["corpus_version"], temperature=float(r["temperature"] or 0), input_hash=r["input_hash"],
            input=r["input"], input_source_ids=list(r["input_source_ids"] or []), output=r["output"],
            output_hash=r["output_hash"], usage=r["usage"] or {}, status=r["status"],
            validation_errors=r["validation_errors"] or [], duration_ms=r["duration_ms"] or 0, error=r["error"],
            registry_id=r["registry_id"] or "", created_at=r["created_at"].isoformat(),
        )

    def save_run(self, run: ModelRunRecord) -> None:
        with self.engine.begin() as conn:
            execute(conn, """
                INSERT INTO ntk.model_runs (id, task_type, provider, model_family, model_version, prompt_version,
                    schema_version, corpus_version, input_hash, input, output, usage, role, temperature, status,
                    validation_errors, output_hash, input_source_ids, duration_ms, error, registry_id)
                VALUES (CAST(:id AS uuid), :task, :prov, :fam, :mv, :pv, :sv, :cv, :ih, CAST(:inp AS jsonb),
                    CAST(:out AS jsonb), CAST(:usage AS jsonb), :role, :temp, :st, CAST(:ve AS jsonb), :oh, :src, :dur,
                    CAST(:err AS jsonb), :reg)
                ON CONFLICT (id) DO UPDATE SET output = EXCLUDED.output, status = EXCLUDED.status,
                    validation_errors = EXCLUDED.validation_errors, output_hash = EXCLUDED.output_hash,
                    usage = EXCLUDED.usage, duration_ms = EXCLUDED.duration_ms, error = EXCLUDED.error,
                    model_version = EXCLUDED.model_version
                WHERE ntk.model_runs.status <> 'succeeded'
            """, {"id": run.id, "task": run.task_type, "prov": run.provider, "fam": run.model_family,
                  "mv": run.model_version, "pv": run.prompt_version, "sv": run.schema_version, "cv": run.corpus_version,
                  "ih": run.input_hash, "inp": j(run.input), "out": j(run.output), "usage": j(run.usage),
                  "role": run.role, "temp": run.temperature, "st": run.status, "ve": j(run.validation_errors),
                  "oh": run.output_hash, "src": run.input_source_ids, "dur": run.duration_ms,
                  "err": j(run.error) if run.error else None, "reg": run.registry_id})


def sync_registry(conn: Connection, registry_rows: list[dict]) -> None:
    for r in registry_rows:
        execute(conn, """
            INSERT INTO ntk.model_registry (id, role, provider, model_family, model_id, model_version, context_limit,
                is_lite, allowed_for_final, active)
            VALUES (:id, :role, :provider, :model_family, :model_id, :model_version, :context_limit, :is_lite,
                :allowed_for_final, true)
            ON CONFLICT (id) DO UPDATE SET active = true, is_lite = EXCLUDED.is_lite,
                allowed_for_final = EXCLUDED.allowed_for_final
        """, r)


# ------------------------------------------------------------------ corpus version
def current_corpus_version(conn: Connection) -> str:
    return scalar(conn, "SELECT id FROM ntk.corpus_versions ORDER BY seq DESC LIMIT 1") or "cv-000000"


def bump_corpus_version(conn: Connection, *, reason: str, actor: str) -> str:
    seq = scalar(conn, "SELECT nextval(pg_get_serial_sequence('ntk.corpus_versions','seq'))")
    cid = f"cv-{int(seq):06d}"
    execute(conn, "INSERT INTO ntk.corpus_versions (seq, id, reason, actor) VALUES (:s, :id, :r, :a)",
            {"s": seq, "id": cid, "r": reason[:500], "a": actor})
    return cid


def new_request_id() -> str:
    return uuid.uuid4().hex


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
