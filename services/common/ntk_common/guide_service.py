"""Building and storing reader guides (ADR-0015). Called by the worker task ``ntk.build_guides``."""

from __future__ import annotations

from typing import Any

from . import guides, ids
from .db import knowledge as kdb
from .db import ops, sources
from .db.core import rows, scalar
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
    """Everyone listed as a witness in a published hearing, or named as testifying in a court notice, grouped by name.
    ``hearings`` are hearings with a transcript; ``appearances`` are days known only from a court notice."""
    hs = rows(conn, """
        SELECT h.id, h.hearing_date::text AS hearing_date, h.witnesses, h.source_version_id
        FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE sv.publication_state = 'published' ORDER BY h.hearing_date
    """)
    out: dict[str, dict] = {}

    def entry(name: str, label: str | None) -> dict:
        slug = guides.witness_slug(name)
        return out.setdefault(slug, {"slug": slug, "name": name, "label": label, "raw": set(), "hearings": [],
                                     "appearances": [], "side": None})

    for h in hs:
        for raw in h["witnesses"] or []:
            name, label = guides.witness_name(raw)
            if not name:
                continue
            w = entry(name, label)
            w["raw"].add(raw)
            w["hearings"].append({"id": h["id"], "hearing_date": h["hearing_date"], "source_version_id": h["source_version_id"]})
    for d in published_hearing_days(conn):
        for wt in d["witnesses"]:
            name, label = guides.witness_name(wt["name"])
            if not name:
                continue
            w = entry(name, label)
            if any(a["date"] == d["hearing_date"] for a in w["appearances"]):
                continue
            w["appearances"].append({"date": d["hearing_date"], "side": wt.get("side"), "description": wt.get("description"),
                                     "source_version_id": d["source_version_id"], "document_title": d["document_title"],
                                     "has_transcript": any(h["hearing_date"] == d["hearing_date"] for h in w["hearings"])})
            if wt.get("side") in {"prosecution", "defense"}:
                w["side"] = wt["side"]
    for w in out.values():
        w["raw"] = sorted(w["raw"])
    return sorted(out.values(), key=lambda w: (_all_dates(w)[0], w["name"]))


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


def _save(pipeline, res, *, object_type: str, object_id: str) -> dict:
    if res.payload is None:
        with pipeline.s.engine.begin() as conn:
            ops.audit(conn, actor="pipeline", action="guide.failed", object_type=object_type, object_id=object_id,
                      details={"errors": res.errors[:10]})
        return {"object": f"{object_type}:{object_id}", "state": "failed", "errors": res.errors[:5]}
    writer = next(r.id for r in res.runs if r.task_type != "verify")
    verifier = next((r.id for r in reversed(res.runs) if r.task_type == "verify"), None)
    art_id = str(ids.derived_uuid("guide_artifact", res.payload["id"]))
    with pipeline.s.engine.begin() as conn:
        aid, created = kdb.save_artifact(conn, artifact_id=art_id, artifact_type="guide", object_type=object_type,
                                         object_id=object_id, payload=res.payload, decision=res.decision,
                                         model_run_id=writer, verifier_run_id=verifier)
    report = res.decision.report() if res.decision else {}
    failed = [g["gate"] for g in report.get("gates", []) if not g["passed"]]
    return {"object": f"{object_type}:{object_id}", "artifact_id": aid, "created": created,
            "state": res.decision.state if res.decision else None, "failed_gates": failed,
            "items": sum(len(b["items"]) for b in res.payload["blocks"])}


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
