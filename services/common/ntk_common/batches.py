"""Hearing digests through the provider's Batch API (cost control, 11.10.2026): half the price of direct calls, in
exchange for waiting up to 24 hours.

submit: for hearings without a digest, build the exact first-attempt digest request (same input → same run id as the
        direct path), group requests into batches under a size cap, send them, record each batch.
poll:   when a batch is done, save every answer as the model run with that run id, then build the digest the normal
        way: the builder finds the run in the store and does not call the model; only the rare follow-ups (a retry
        after a wording rejection, the verifier on a few sentences) are made directly. Gates and publication policy
        are unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from .db import ops
from .db.core import execute, j, row, rows
from .layers import digest_input
from .llm.prompts import ALL as PROMPTS

MAX_BATCH_BYTES = 15_000_000  # inline batch requests must stay well under the provider's 20 MB limit
FINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")


def _hearings_without_digest(conn, hearing_ids: list[str] | None, limit: int) -> list[dict]:
    return rows(conn, """
        SELECT h.id, h.source_version_id FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE (CAST(:ids AS text[]) IS NULL OR h.id = ANY(:ids))
          AND NOT EXISTS (SELECT 1 FROM ntk.generated_artifacts ga WHERE ga.object_type = 'hearing' AND ga.object_id = h.id
                            AND ga.review_state IN ('machine_verified', 'human_review_required', 'approved', 'published'))
          AND NOT EXISTS (SELECT 1 FROM ntk.model_batches b, jsonb_array_elements(b.items) it
                          WHERE b.finished_at IS NULL AND it->>'hearing_id' = h.id)
        ORDER BY h.hearing_date LIMIT :lim""", {"ids": hearing_ids, "lim": limit})


def submit_digests(pipeline, *, hearing_ids: list[str] | None = None, limit: int = 200) -> dict:
    runner = pipeline.s.runner
    with pipeline.s.engine.connect() as conn:
        hearings = _hearings_without_digest(conn, hearing_ids, limit)
    items: list[dict] = []
    for h in hearings:
        units, exchanges, _cv = pipeline.digest_material(h["id"], h["source_version_id"])
        if not units:
            continue
        req = runner.request_for("digest", digest_input(hearing_id=h["id"], units=units, exchanges=exchanges))
        cached = runner.store.get_run(req["run_id"])
        if cached is not None and cached.ok:  # already answered (e.g. an earlier batch): build directly, no cost
            pipeline.rebuild_hearing_digest(h["id"])
            continue
        provider = runner.provider_for(req["spec"])
        body = provider.request_body(system=req["prompt"].system, user=req["user"], temperature=req["spec"].temperature,
                                     response_schema=req["response_schema"])
        items.append({"key": f"digest|{req['run_id']}", "request": body, "hearing_id": h["id"], "run_id": req["run_id"],
                      "input_hash": req["input_hash"], "role": req["role"], "model_id": req["spec"].model_id,
                      "bytes": len(json.dumps(body, ensure_ascii=False).encode("utf-8"))})
    groups: list[list[dict]] = []
    for it in items:
        if not groups or sum(x["bytes"] for x in groups[-1]) + it["bytes"] > MAX_BATCH_BYTES:
            groups.append([])
        groups[-1].append(it)
    submitted = []
    for gi, group in enumerate(groups):
        model_id = group[0]["model_id"]
        provider = runner.provider_for(runner.registry.get(group[0]["role"]))
        name = provider.create_batch(model_id=model_id, items=[{"key": x["key"], "request": x["request"]} for x in group],
                                     display_name=f"ntk-digests-{gi + 1}")
        meta = [{k: x[k] for k in ("key", "hearing_id", "run_id", "input_hash", "role", "bytes")} for x in group]
        with pipeline.s.engine.begin() as conn:
            execute(conn, """INSERT INTO ntk.model_batches (name, task_type, model_id, items) VALUES (:n, 'digest', :m, CAST(:i AS jsonb))
                             ON CONFLICT (name) DO NOTHING""", {"n": name, "m": model_id, "i": j(meta)})
            ops.audit(conn, actor="worker", action="batch.submitted", object_type="model_batch", object_id=name,
                      details={"task": "digest", "items": len(group), "bytes": sum(x["bytes"] for x in group)})
        submitted.append({"name": name, "items": len(group)})
    return {"hearings": len(hearings), "requests": len(items), "batches": submitted}


def poll(pipeline) -> dict:
    runner = pipeline.s.runner
    with pipeline.s.engine.connect() as conn:
        open_batches = rows(conn, "SELECT * FROM ntk.model_batches WHERE finished_at IS NULL ORDER BY created_at")
    out = []
    for b in open_batches:
        provider = runner.provider_for(runner.registry.get(b["items"][0]["role"] if b["items"] else "extractor"))
        st = provider.get_batch(b["name"])
        state = st["state"] or "unknown"
        if not st["done"]:
            with pipeline.s.engine.begin() as conn:
                execute(conn, "UPDATE ntk.model_batches SET state = :s, updated_at = now() WHERE name = :n",
                        {"s": state, "n": b["name"]})
            out.append({"name": b["name"], "state": state})
            continue
        built: list[dict[str, Any]] = []
        for it in b["items"]:
            res = st["responses"].get(it["key"])
            if res is None or isinstance(res, dict):
                built.append({"hearing_id": it["hearing_id"], "error": (res or {}).get("error", "no response")})
                continue
            req = {"run_id": it["run_id"], "task_type": "digest", "role": it["role"], "spec": runner.registry.get(it["role"]),
                   "prompt": PROMPTS["digest"], "input_hash": it["input_hash"]}
            with pipeline.s.engine.connect() as conn:
                cv = ops.current_corpus_version(conn)
            run = runner.record(req, res, payload=None, input_source_ids=[], corpus_version=cv)
            if not run.ok:
                built.append({"hearing_id": it["hearing_id"], "error": "invalid output", "details": run.validation_errors[:3]})
                continue
            try:
                r = pipeline.rebuild_hearing_digest(it["hearing_id"])
                built.append({"hearing_id": it["hearing_id"], "digest_id": r.get("digest_id"), "state": r.get("state"),
                              "auto_published": r.get("auto_published")})
            except Exception as exc:  # noqa: BLE001 - one hearing must not stop the batch
                built.append({"hearing_id": it["hearing_id"], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        with pipeline.s.engine.begin() as conn:
            execute(conn, """UPDATE ntk.model_batches SET state = :s, updated_at = now(), finished_at = now(),
                             result = CAST(:r AS jsonb), error = CAST(:e AS jsonb) WHERE name = :n""",
                    {"s": state, "n": b["name"], "r": j({"built": built}), "e": j(st.get("error")) if st.get("error") else None})
            ops.audit(conn, actor="worker", action="batch.finished", object_type="model_batch", object_id=b["name"],
                      details={"state": state, "built": len([x for x in built if x.get("digest_id")]),
                               "errors": len([x for x in built if x.get("error")])})
        out.append({"name": b["name"], "state": state, "built": built})
    return {"batches": out}


def listing(conn, limit: int = 50) -> list[dict]:
    return rows(conn, """SELECT name, task_type, model_id, state, jsonb_array_length(items) AS items, created_at, updated_at,
                                finished_at, result, error FROM ntk.model_batches ORDER BY created_at DESC LIMIT :l""",
                {"l": limit})


_ = row
