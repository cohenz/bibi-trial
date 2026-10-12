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
from .llm.providers import ProviderError

MAX_BATCH_BYTES = 15_000_000  # inline batch requests must stay well under the provider's 20 MB limit
FINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")


def with_schema_text(user: str, schema: dict | None) -> str:
    """The batch endpoint ignores ``responseJsonSchema`` (pilot 11.10.2026: all 10 answers were free-form JSON), so the
    output contract is also written into the prompt, as the direct path does when the API rejects the schema. The run
    id is unchanged (it is derived from the logical input, not the request body)."""
    if not schema:
        return user
    return user + "\n<output_json_schema>\n" + json.dumps(schema, ensure_ascii=False) + "\n</output_json_schema>"


def _hearings_without_digest(conn, hearing_ids: list[str] | None, limit: int) -> list[dict]:
    """Hearings an approval may spend a request on. Without explicit ids, a hearing whose digest was already rejected is
    skipped: its stored answer would be rebuilt (free) and rejected again, yet still count against the approval
    (12.10.2026: 45 of an approved 182 were spent this way and 42 hearings were never sent). Retry those by id."""
    states = ["machine_verified", "human_review_required", "approved", "published"]
    if hearing_ids is None:
        states.append("rejected")
    return rows(conn, """
        SELECT h.id, h.source_version_id FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE (CAST(:ids AS text[]) IS NULL OR h.id = ANY(:ids))
          AND NOT EXISTS (SELECT 1 FROM ntk.generated_artifacts ga WHERE ga.object_type = 'hearing' AND ga.object_id = h.id
                            AND ga.review_state::text = ANY(:states))
          AND NOT EXISTS (SELECT 1 FROM ntk.model_batches b, jsonb_array_elements(b.items) it
                          WHERE b.finished_at IS NULL AND it->>'hearing_id' = h.id)
        ORDER BY h.hearing_date LIMIT :lim""", {"ids": hearing_ids, "lim": limit, "states": states})


MAX_BATCH_ITEMS = 10  # the provider caps tokens waiting in batches; ~10 long protocols fit (12.10.2026)


def _is_quota(exc: Exception) -> bool:
    return isinstance(exc, ProviderError) and getattr(exc, "status", None) == 429


def _create_split(provider, model_id: str, group: list[dict], label: str) -> tuple[list[tuple[str, list[dict]]], list[dict], str | None]:
    """Send a group; when the provider refuses it for quota (HTTP 429), send each half instead, down to single
    requests. Returns (sent [(batch name, items)], not sent items, last quota error)."""
    try:
        name = provider.create_batch(model_id=model_id, items=[{"key": x["key"], "request": x["request"]} for x in group],
                                     display_name=label)
        return [(name, group)], [], None
    except ProviderError as exc:
        if not _is_quota(exc):
            raise
        if len(group) == 1:
            return [], group, str(exc)[:300]
        mid = len(group) // 2
        sent_a, left_a, err_a = _create_split(provider, model_id, group[:mid], label + "a")
        if left_a:  # the first half did not fit: the second will not either
            return sent_a, left_a + group[mid:], err_a
        sent_b, left_b, err_b = _create_split(provider, model_id, group[mid:], label + "b")
        return sent_a + sent_b, left_b, err_b


def allowance(conn, task_type: str = "digest") -> dict:
    r = row(conn, "SELECT * FROM ntk.batch_allowance WHERE task_type = :t", {"t": task_type})
    return dict(r) if r else {"task_type": task_type, "remaining": 0, "approved_total": 0, "approved_by": None,
                              "last_error": None, "updated_at": None}


def _set_allowance(engine, remaining: int, *, approved_total: int | None = None, by: str | None = None,
                   error: str | None = None) -> None:
    with engine.begin() as conn:
        execute(conn, """
            INSERT INTO ntk.batch_allowance (task_type, remaining, approved_total, approved_by, last_error, updated_at)
            VALUES ('digest', :r, COALESCE(:t, 0), :b, :e, now())
            ON CONFLICT (task_type) DO UPDATE SET remaining = :r,
                approved_total = COALESCE(:t, ntk.batch_allowance.approved_total),
                approved_by = COALESCE(:b, ntk.batch_allowance.approved_by), last_error = :e, updated_at = now()""",
                {"r": max(0, remaining), "t": approved_total, "b": by, "e": error})


def submit_digests(pipeline, *, hearing_ids: list[str] | None = None, limit: int = 200, approved_by: str | None = None,
                   from_allowance: bool = False) -> dict:
    """Send up to ``limit`` first-attempt digest requests through the Batch API.

    What the provider does not accept now (its cap on tokens waiting in batches) is kept as an allowance and sent by
    ``poll`` as earlier batches finish, so an approval of N is honoured in full but never exceeded. A new approval
    replaces what was left of the previous one; ``limit=0`` cancels it."""
    runner = pipeline.s.runner
    with pipeline.s.engine.connect() as conn:
        hearings = _hearings_without_digest(conn, hearing_ids, limit) if limit > 0 else []
    items: list[dict] = []
    built_directly = 0
    failed: list[dict] = []
    for h in hearings:
        units, exchanges, _cv = pipeline.digest_material(h["id"], h["source_version_id"])
        if not units:
            continue
        req = runner.request_for("digest", digest_input(hearing_id=h["id"], units=units, exchanges=exchanges))
        cached = runner.store.get_run(req["run_id"])
        if cached is not None and cached.ok:  # already answered (e.g. an earlier batch): build directly
            try:
                pipeline.rebuild_hearing_digest(h["id"])
                built_directly += 1
            except Exception as exc:  # noqa: BLE001 - one hearing must not block the rest of the approval
                failed.append({"hearing_id": h["id"], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            continue
        provider = runner.provider_for(req["spec"])
        body = provider.request_body(system=req["prompt"].system, user=with_schema_text(req["user"], req["response_schema"]),
                                     temperature=req["spec"].temperature, response_schema=req["response_schema"])
        items.append({"key": f"digest|{req['run_id']}", "request": body, "hearing_id": h["id"], "run_id": req["run_id"],
                      "input_hash": req["input_hash"], "role": req["role"], "model_id": req["spec"].model_id,
                      "bytes": len(json.dumps(body, ensure_ascii=False).encode("utf-8"))})
    groups: list[list[dict]] = []
    for it in items:
        if (not groups or len(groups[-1]) >= MAX_BATCH_ITEMS
                or sum(x["bytes"] for x in groups[-1]) + it["bytes"] > MAX_BATCH_BYTES):
            groups.append([])
        groups[-1].append(it)
    submitted: list[dict] = []
    not_sent: list[dict] = []
    quota_error = None
    for gi, group in enumerate(groups):
        if quota_error:  # the provider is full: keep the rest for later
            not_sent.extend(group)
            continue
        model_id = group[0]["model_id"]
        provider = runner.provider_for(runner.registry.get(group[0]["role"]))
        sent, left, err = _create_split(provider, model_id, group, f"ntk-digests-{gi + 1}")
        not_sent.extend(left)
        quota_error = err
        for name, part in sent:
            meta = [{k: x[k] for k in ("key", "hearing_id", "run_id", "input_hash", "role", "bytes")} for x in part]
            with pipeline.s.engine.begin() as conn:
                execute(conn, """INSERT INTO ntk.model_batches (name, task_type, model_id, items) VALUES (:n, 'digest', :m, CAST(:i AS jsonb))
                                 ON CONFLICT (name) DO NOTHING""", {"n": name, "m": model_id, "i": j(meta)})
                ops.audit(conn, actor="worker", action="batch.submitted", object_type="model_batch", object_id=name,
                          details={"task": "digest", "items": len(part), "bytes": sum(x["bytes"] for x in part)})
            submitted.append({"name": name, "items": len(part)})
    n_sent = sum(b["items"] for b in submitted)
    done = n_sent + built_directly
    if hearing_ids is None:
        if from_allowance:
            with pipeline.s.engine.connect() as conn:
                left_allowance = allowance(conn)["remaining"] - done
        else:
            left_allowance = limit - done
        _set_allowance(pipeline.s.engine, left_allowance, approved_total=None if from_allowance else limit,
                       by=None if from_allowance else approved_by, error=quota_error)
    return {"hearings": len(hearings), "requests": len(items), "batches": submitted, "built_directly": built_directly,
            "not_sent_now": len(not_sent), "quota_full": bool(quota_error), "failed": failed}


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
            # An invalid batch answer is not resubmitted (the same request would likely fail the same way): the build
            # below finds no valid run and makes one direct call with schema-constrained decoding.
            try:
                r = pipeline.rebuild_hearing_digest(it["hearing_id"])
                built.append({"hearing_id": it["hearing_id"], "digest_id": r.get("digest_id"), "state": r.get("state"),
                              "auto_published": r.get("auto_published"), "via": "batch" if run.ok else "direct_fallback",
                              **({} if run.ok else {"batch_errors": run.validation_errors[:2]})})
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
    res: dict[str, Any] = {"batches": out}
    with pipeline.s.engine.connect() as conn:
        left = allowance(conn)["remaining"]
    if left > 0:  # approved requests the provider could not take earlier: send what it takes now
        try:
            res["submitted"] = submit_digests(pipeline, limit=left, from_allowance=True)
        except Exception as exc:  # noqa: BLE001 - collecting finished batches must not fail because of sending
            res["submit_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return res


def listing(conn, limit: int = 50) -> list[dict]:
    """Recent batches (the remaining approved allowance is in ``allowance()``)."""
    return rows(conn, """SELECT name, task_type, model_id, state, jsonb_array_length(items) AS items, created_at, updated_at,
                                finished_at, result, error FROM ntk.model_batches ORDER BY created_at DESC LIMIT :l""",
                {"l": limit})


_ = row
