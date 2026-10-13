"""Building and storing reader guides (ADR-0015). Called by the worker task ``ntk.build_guides``."""

from __future__ import annotations

from typing import Any

from . import contracts, gates, guides, ids, people
from .db import knowledge as kdb
from .db import ops, sources
from .db.core import execute, rows, scalar
from .db.public import units_by_ids
from .layers import UnitView

MAX_UNITS_PER_HEARING = 90


def _units_for_version(conn, svid: str) -> list[UnitView]:
    unit_rows = sources.units_for_version(conn, svid)
    views = units_by_ids(conn, [r["id"] for r in unit_rows], published_only=False)
    return [views[r["id"]] for r in unit_rows if r["id"] in views]


def latest_indictment(conn) -> str | None:
    return scalar(conn, """
        SELECT sv.id FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
        WHERE d.source_type = 'indictment' AND sv.publication_state = 'published'
        ORDER BY coalesce(sv.metadata->>'document_date', '') DESC, sv.created_at DESC LIMIT 1
    """)


def published_hearing_days(conn) -> list[dict]:
    """Hearing days recorded in published document briefs (court notices: who testified, when)."""
    out = []
    for r in rows(conn, """
        SELECT ga.object_id AS sv, ga.payload FROM ntk.generated_artifacts ga
        JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
        WHERE ga.artifact_type = 'summary' AND ga.object_type = 'document'
          AND jsonb_array_length(coalesce(ga.payload->'hearing_days', '[]'::jsonb)) > 0"""):
        for d in r["payload"]["hearing_days"]:
            out.append({**d, "source_version_id": r["sv"], "document_title": r["payload"]["title"]["text"]})
    return sorted(out, key=lambda d: d["hearing_date"])


def _all_dates(w: dict) -> list[str]:
    return sorted([h["hearing_date"] for h in w["hearings"]] + [a["date"] for a in w["appearances"]])


def witnesses(conn) -> list[dict]:
    """Everyone listed as a witness in a published hearing, or named as testifying in a court notice, one entry per
    person (``people.Resolver``: titles, word order, spelling variants and checked aliases are folded together).
    ``hearings`` are hearings with a transcript; ``appearances`` are days known only from a court notice.
    ``aliases`` are slugs the same person had before the names were folded (old links keep working);
    ``variants`` are the strings as printed (the site links any of them to the person)."""
    hs = rows(conn, """
        SELECT h.id, h.hearing_date::text AS hearing_date, h.witnesses, h.source_version_id
        FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE sv.publication_state = 'published' ORDER BY h.hearing_date
    """)
    days = published_hearing_days(conn)
    res = people.Resolver()
    for h in hs:
        for raw in h["witnesses"] or []:
            res.add(raw, h["hearing_date"])
    for d in days:
        for wt in d["witnesses"]:
            res.add(wt["name"], d["hearing_date"])
    who = res.resolve()
    out: dict[int, dict] = {}

    def entry(raw: str) -> dict | None:
        p = who.get(raw)
        if p is None:
            return None
        w = out.get(id(p))
        if w is None:
            slug = guides.witness_slug(p.name)
            w = out[id(p)] = {"slug": slug, "name": p.name, "label": p.label, "raw": set(), "hearings": [],
                              "appearances": [], "side": None, "aliases": set(), "variants": set(p.forms)}
        w["raw"].add(raw)
        w["variants"].add(raw)
        legacy = guides.witness_slug(guides.witness_name(raw)[0])  # the slug before names were folded
        if legacy != w["slug"]:
            w["aliases"].add(legacy)
        return w

    for h in hs:
        for raw in h["witnesses"] or []:
            w = entry(raw)
            if w is None or any(x["id"] == h["id"] for x in w["hearings"]):
                continue
            w["hearings"].append({"id": h["id"], "hearing_date": h["hearing_date"], "source_version_id": h["source_version_id"]})
    for d in days:
        for wt in d["witnesses"]:
            w = entry(wt["name"])
            if w is None:
                continue
            if wt.get("side") in {"prosecution", "defense"}:
                w["side"] = wt["side"]
            if any(a["date"] == d["hearing_date"] for a in w["appearances"]):
                continue
            w["appearances"].append({"date": d["hearing_date"], "side": wt.get("side"), "description": wt.get("description"),
                                     "source_version_id": d["source_version_id"], "document_title": d["document_title"],
                                     "has_transcript": any(h["hearing_date"] == d["hearing_date"] for h in w["hearings"])})
    for w in out.values():
        w["raw"] = sorted(w["raw"])
        w["aliases"] = sorted(w["aliases"])
        w["variants"] = sorted(w["variants"])
    return sorted(out.values(), key=lambda w: (_all_dates(w)[0], w["name"]))


def slug_by_raw(ws: list[dict]) -> dict[str, dict]:
    """Printed witness string → its person entry (for hearing pages and the timeline)."""
    return {raw: w for w in ws for raw in w["variants"]}


def _sample(units: list[UnitView], keep: set[str], n: int) -> list[UnitView]:
    """Keep the digest-cited units and an even spread of the rest, in order."""
    if len(units) <= n:
        return units
    must = [u for u in units if u.id in keep][: n // 2]
    rest = [u for u in units if u.id not in keep]
    step = max(1, len(rest) // max(1, n - len(must)))
    chosen = {u.id for u in must} | {u.id for u in rest[::step][: n - len(must)]}
    return [u for u in units if u.id in chosen]


def witness_hearings(conn, w: dict) -> list[guides.WitnessHearing]:
    out = []
    for h in w["hearings"]:
        unit_rows = rows(conn, """
            SELECT id FROM ntk.source_units WHERE hearing_id = :h AND superseded_at IS NULL
              AND witness_label = ANY(:raw) AND unit_type IN ('question', 'answer', 'speech_turn')
            ORDER BY unit_ordinal""", {"h": h["id"], "raw": w["raw"]})
        views = units_by_ids(conn, [r["id"] for r in unit_rows], published_only=True)
        units = [views[r["id"]] for r in unit_rows if r["id"] in views]
        cited = set(scalar(conn, """
            SELECT coalesce(array_agg(DISTINCT c->>'source_unit_id'), '{}') FROM ntk.generated_artifacts ga
            JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL,
            jsonb_array_elements(ga.payload->'citations') c
            WHERE ga.artifact_type = 'summary' AND ga.object_type = 'hearing' AND ga.object_id = :h""", {"h": h["id"]}) or [])
        if units:
            out.append(guides.WitnessHearing(h["id"], h["hearing_date"], _sample(units, cited, MAX_UNITS_PER_HEARING)))
    return out


def _hold(conn, slug: str) -> str | None:
    """An operator's hold on a witness guide (irrelevant or merely procedural testimony): it never publishes by policy."""
    r = rows(conn, """SELECT action, details FROM ntk.audit_events WHERE object_type = 'witness' AND object_id = :s
                      AND action IN ('guide.policy.hold', 'guide.policy.release') ORDER BY occurred_at DESC LIMIT 1""",
             {"s": slug})
    if not r or r[0]["action"] != "guide.policy.hold":
        return None
    return (r[0]["details"] or {}).get("reason") or "הושאר לבדיקה"


def _store(pipeline, payload: dict, decision, *, object_type: str, object_id: str, writer: str | None,
           verifier: str | None) -> tuple[str, bool, bool]:
    """Save a guide version; a witness guide that the policy clears is published right away (NTK_AUTO_PUBLISH=gates)."""
    art_id = str(ids.derived_uuid("guide_artifact", payload["id"]))
    with pipeline.s.engine.begin() as conn:
        aid, created = kdb.save_artifact(conn, artifact_id=art_id, artifact_type="guide", object_type=object_type,
                                         object_id=object_id, payload=payload, decision=decision,
                                         model_run_id=writer, verifier_run_id=verifier)
    published = pipeline.auto_publish(aid, decision) if decision.state == "machine_verified" else False
    return aid, created, published


def _wait_note(pipeline, artifact_id: str, reason: str) -> None:
    """The review screen shows the part after " — " as "why this waits for you"."""
    with pipeline.s.engine.begin() as conn:
        execute(conn, """UPDATE ntk.review_tasks SET reason = left(split_part(reason, ' — ', 1) || ' — ' || :r, 500),
                                updated_at = now()
                         WHERE object_type = 'artifact' AND object_id = :a AND status = 'open'""",
                {"a": artifact_id, "r": reason})


def _save(pipeline, res, *, object_type: str, object_id: str) -> dict:
    if res.payload is None:
        with pipeline.s.engine.begin() as conn:
            ops.audit(conn, actor="pipeline", action="guide.failed", object_type=object_type, object_id=object_id,
                      details={"errors": res.errors[:10]})
        return {"object": f"{object_type}:{object_id}", "state": "failed", "errors": res.errors[:5]}
    writer = next(r.id for r in res.runs if r.task_type != "verify")
    verifier = next((r.id for r in reversed(res.runs) if r.task_type == "verify"), None)
    payload, decision, extra = res.payload, res.decision, {}
    if object_type == "witness" and decision is not None and pipeline.cfg.auto_publish == "gates":
        with pipeline.s.engine.connect() as conn:
            hold = _hold(conn, object_id)
        out = guides.witness_policy(payload, decision, hold=hold)
        if out.publish:
            contracts.validate("GuideObject", out.payload)
            payload, decision = out.payload, out.decision
            extra = {"dropped": out.dropped}
        else:
            extra = {"waits": out.reason}
    aid, created, published = _store(pipeline, payload, decision, object_type=object_type, object_id=object_id,
                                     writer=writer, verifier=verifier)
    if extra.get("waits") and decision.state != "rejected":
        _wait_note(pipeline, aid, extra["waits"])
    report = decision.report() if decision else {}
    failed = [g["gate"] for g in report.get("gates", []) if not g["passed"]]
    return {"object": f"{object_type}:{object_id}", "artifact_id": aid, "created": created,
            "state": "published" if published else (decision.state if decision else None), "failed_gates": failed,
            "items": sum(len(b["items"]) for b in payload["blocks"]), **extra}


def apply_witness_policy(pipeline, *, keys: list[str] | None = None, holds: dict[str, str] | None = None,
                         release: list[str] | None = None, apply: bool = False, actor: str = "operator") -> dict:
    """Run the witness-guide policy over guides already waiting in the review queue (built before the policy, or
    released from a hold). ``holds``: slug → reason (irrelevant / procedural) — recorded, and those guides wait."""
    holds, release = holds or {}, release or []
    if apply and (holds or release):
        with pipeline.s.engine.begin() as conn:
            for slug, reason in holds.items():
                ops.audit(conn, actor=actor, action="guide.policy.hold", object_type="witness", object_id=slug,
                          details={"reason": reason})
            for slug in release:
                ops.audit(conn, actor=actor, action="guide.policy.release", object_type="witness", object_id=slug)
    with pipeline.s.engine.connect() as conn:
        waiting = rows(conn, """SELECT DISTINCT ON (object_id) id, object_id, payload, gate_report, model_run_id,
                                       verifier_run_id, review_state::text AS st
                                FROM ntk.generated_artifacts
                                WHERE artifact_type = 'guide' AND object_type = 'witness'
                                  AND review_state = 'human_review_required'
                                ORDER BY object_id, created_at DESC""")
        held = {w["object_id"]: holds.get(w["object_id"]) or (None if w["object_id"] in release else _hold(conn, w["object_id"]))
                for w in waiting}
    out: dict[str, list] = {"published": [], "waits": [], "errors": []}
    for w in waiting:
        slug = w["object_id"]
        if keys and slug not in keys:
            continue
        payload = w["payload"]
        res = guides.witness_policy(payload, gates.GateDecision.from_report(w["gate_report"]), hold=held[slug])
        entry = {"slug": slug, "name": payload.get("title"), "artifact_id": str(w["id"])}
        if not res.publish:
            out["waits"].append({**entry, "reason": res.reason})
            if apply:
                _wait_note(pipeline, str(w["id"]), res.reason or "")
            continue
        entry["dropped"] = res.dropped
        if apply:
            try:
                contracts.validate("GuideObject", res.payload)
                aid, _created, published = _store(pipeline, res.payload, res.decision, object_type="witness", object_id=slug,
                                                  writer=str(w["model_run_id"]) if w["model_run_id"] else None,
                                                  verifier=str(w["verifier_run_id"]) if w["verifier_run_id"] else None)
                entry.update(artifact_id=aid, published=published)
            except Exception as exc:  # noqa: BLE001 — one guide must not stop the rest
                out["errors"].append({**entry, "error": str(exc)[:300]})
                continue
        out["published"].append(entry)
    out["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    return out


def build(pipeline, *, kind: str = "all", source_version_id: str | None = None, keys: list[str] | None = None) -> dict:
    """kind: indictment | cases | witnesses | all. Returns what was built."""
    cfg = pipeline.cfg
    out: dict[str, Any] = {"built": []}
    with pipeline.s.engine.connect() as conn:
        svid = source_version_id or latest_indictment(conn)
        cv = ops.current_corpus_version(conn)
        ind_units = _units_for_version(conn, svid) if svid else []
    common = {"runner": pipeline.s.runner, "corpus_version": cv, "citation_base": cfg.citation_base, "env": cfg.env}
    if kind in {"indictment", "cases", "all"}:
        if not svid:
            return {"error": "no published indictment"}
        parts = guides.split_indictment(ind_units)
        if not parts.count_order:
            return {"error": "no counts found in the indictment", "source_version_id": svid, "units": len(ind_units)}
        out["indictment"] = {"source_version_id": svid, "counts": {k: len(v) for k, v in parts.counts.items()},
                             "general": len(parts.general), "appendices": {k: len(v) for k, v in parts.appendices.items()}}
        if kind in {"indictment", "all"}:
            res = guides.build_indictment_overview(parts=parts, source_version_id=svid, **common)
            out["built"].append(_save(pipeline, res, object_type="indictment", object_id="main"))
        if kind in {"cases", "all"}:
            for key in parts.count_order:
                if keys and key not in keys:
                    continue
                res = guides.build_case_guide(case_key=key, parts=parts, source_version_id=svid, **common)
                out["built"].append(_save(pipeline, res, object_type="case", object_id=key))
    if kind in {"witnesses", "all"}:
        with pipeline.s.engine.connect() as conn:
            ws = witnesses(conn)
        for w in ws:
            if keys and w["slug"] not in keys:
                continue
            with pipeline.s.engine.connect() as conn:
                hearings = witness_hearings(conn, w)
            if not hearings:
                continue
            res = guides.build_witness_guide(name=w["name"], slug=w["slug"], hearings=hearings, indictment_units=ind_units,
                                             source_version_ids=sorted({h["source_version_id"] for h in w["hearings"]}),
                                             **common)
            out["built"].append(_save(pipeline, res, object_type="witness", object_id=w["slug"]))
    return out
