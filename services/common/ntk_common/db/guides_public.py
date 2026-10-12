"""Public read models for reader guides (ADR-0015). Only published guides and published sources are returned."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from .. import guides, hebrew
from ..guide_service import slug_by_raw
from ..guide_service import witnesses as all_witnesses
from .core import row, rows
from .public import public_documents, public_hearings, units_by_ids


def _brackets(text: str) -> str:
    return "\n".join(hebrew.fix_bracket_direction(ln) for ln in (text or "").split("\n"))


CASE_ORDER = {"4000": 0, "2000": 1, "1000": 2}


def published_guide(conn: Connection, object_type: str, object_id: str) -> dict | None:
    r = row(conn, """
        SELECT ga.id::text AS id, ga.payload, p.published_at FROM ntk.generated_artifacts ga
        JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
        WHERE ga.artifact_type = 'guide' AND ga.object_type = :ot AND ga.object_id = :oid
        ORDER BY p.published_at DESC LIMIT 1
    """, {"ot": object_type, "oid": object_id})
    if r is None:
        return None
    return {**r["payload"], "artifact_id": r["id"], "published_at": r["published_at"]}


def published_guides(conn: Connection, object_type: str) -> list[dict]:
    rs = rows(conn, """
        SELECT DISTINCT ON (ga.object_id) ga.id::text AS id, ga.object_id, ga.payload FROM ntk.generated_artifacts ga
        JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
        WHERE ga.artifact_type = 'guide' AND ga.object_type = :ot
        ORDER BY ga.object_id, p.published_at DESC
    """, {"ot": object_type})
    return [{**r["payload"], "artifact_id": r["id"]} for r in rs]


def block(g: dict, name: str) -> list[dict]:
    return next((b["items"] for b in g.get("blocks", []) if b["block"] == name), [])


def _indictment_document(conn: Connection, svid: str | None) -> dict | None:
    if not svid:
        return None
    return row(conn, """
        SELECT sv.id AS source_version_id, d.canonical_title AS title, coalesce(sv.metadata->>'document_date', '') AS document_date,
               sv.page_count FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
        WHERE sv.id = :sv AND sv.publication_state = 'published'
    """, {"sv": svid})


def _witness_cases(cases: list[dict], ws: list[dict]) -> dict[str, list[str]]:
    """slug → case keys whose 'people' block names the witness."""
    out: dict[str, list[str]] = {}
    for w in ws:
        for c in cases:
            if any(guides.name_matches(w["name"], it.get("label") or "") for it in block(c, "people")):
                out.setdefault(w["slug"], []).append(c["key"])
    return out


def _witness_summary(ws: list[dict], wcases: dict[str, list[str]], with_guides: set[str]) -> list[dict]:
    from ..guide_service import _all_dates

    return [{"slug": w["slug"], "name": w["name"], "label": w["label"], "hearing_count": len(w["hearings"]),
             "appearance_count": len([a for a in w["appearances"] if not a["has_transcript"]]), "side": w.get("side"),
             "first_date": _all_dates(w)[0], "last_date": _all_dates(w)[-1],
             "cases": sorted(wcases.get(w["slug"], []), key=lambda k: CASE_ORDER.get(k, 9)),
             "has_guide": w["slug"] in with_guides or any(a in with_guides for a in w.get("aliases", [])),
             "aliases": w.get("aliases", []), "variants": w.get("variants", [])} for w in ws]


def _hearing_digest(conn: Connection, hearing_id: str) -> dict | None:
    r = row(conn, """
        SELECT ga.payload FROM ntk.generated_artifacts ga JOIN ntk.publications p ON p.artifact_id = ga.id
        AND p.unpublished_at IS NULL WHERE ga.artifact_type = 'summary' AND ga.object_type = 'hearing' AND ga.object_id = :h
        ORDER BY p.published_at DESC LIMIT 1""", {"h": hearing_id})
    return r["payload"] if r else None


def home(conn: Connection) -> dict:
    ind = published_guide(conn, "indictment", "main")
    cases = sorted(published_guides(conn, "case"), key=lambda c: CASE_ORDER.get(c["key"], 9))
    ws = all_witnesses(conn)
    wcases = _witness_cases(cases, ws)
    with_guides = {g["key"] for g in published_guides(conn, "witness")}
    hearings = public_hearings(conn)
    latest = None
    for h in reversed(hearings):
        d = _hearing_digest(conn, h["id"])
        if d:
            sents = d["summary_sentences"][:2]
            ids_ = {c for s in sents for c in s["citation_ids"]}
            latest = {"id": h["id"], "hearing_date": h["hearing_date"], "witnesses": h["witnesses"],
                      "summary_sentences": sents, "citations": [c for c in d["citations"] if c["source_unit_id"] in ids_]}
            break
    counts = rows(conn, """
        SELECT d.source_type::text AS t, count(*) AS n FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
        WHERE sv.publication_state = 'published' AND d.source_type <> 'protocol' GROUP BY 1""")
    return {
        "indictment": None if ind is None else {
            "artifact_id": ind["artifact_id"], "title": ind["title"],
            "document": _indictment_document(conn, (ind.get("source_version_ids") or [None])[0]),
            "blocks": ind["blocks"], "citations": ind["citations"]},
        "cases": [{"key": c["key"], "title": c["title"], "subtitle": c.get("subtitle"),
                   "one_line": (block(c, "one_line") or [None])[0],
                   "defendants": [it["label"] for it in block(c, "charges") if it.get("label")],
                   "charges": [{"label": it.get("label"), "text": it["text"]} for it in block(c, "charges")],
                   "event_count": len(block(c, "events"))} for c in cases],
        "witnesses": _witness_summary(ws, wcases, with_guides),
        "latest_hearing": latest,
        "counts": {"hearings": len(hearings), "documents": {r["t"]: r["n"] for r in counts}},
    }


def case_page(conn: Connection, key: str) -> dict | None:
    g = published_guide(conn, "case", key)
    if g is None:
        return None
    ws = all_witnesses(conn)
    hearing_ids: dict[str, dict] = {}
    for it in block(g, "people"):
        w = next((w for w in ws if guides.name_matches(w["name"], it.get("label") or "")), None)
        if w:
            it["witness_slug"] = w["slug"]
            for h in w["hearings"]:
                hearing_ids[h["id"]] = h
    hs = [h for h in public_hearings(conn) if h["id"] in hearing_ids]
    return {**g, "hearings": [{"id": h["id"], "hearing_date": h["hearing_date"], "witnesses": h["witnesses"]} for h in hs],
            "document": _indictment_document(conn, (g.get("source_version_ids") or [None])[0])}


def witness_page(conn: Connection, slug: str) -> dict | None:
    w = next((w for w in all_witnesses(conn) if w["slug"] == slug or slug in w.get("aliases", [])), None)
    if w is None:
        return None
    requested, slug = slug, w["slug"]  # an old slug of a folded name answers with the person's page
    g = published_guide(conn, "witness", slug) or next(
        (x for x in (published_guide(conn, "witness", a) for a in w.get("aliases", [])) if x), None)
    cases = published_guides(conn, "case")
    citations: dict[str, dict] = {c["source_unit_id"]: c for c in (g or {}).get("citations", [])}
    hearings, notable = [], []
    for h in w["hearings"]:
        d = _hearing_digest(conn, h["id"])
        sents = []
        if d:
            sents = [s for s in d["summary_sentences"] if guides.name_matches(w["name"], s["text"])][:4]
            for c in d["citations"]:
                if any(c["source_unit_id"] in s["citation_ids"] for s in sents):
                    citations[c["source_unit_id"]] = c
            ex = d.get("notable_exchanges") or []
            if ex:
                views = units_by_ids(conn, [u for e in ex for u in (e["question_unit_id"], e["answer_unit_id"])], published_only=True)
                for e in ex:
                    q, a = views.get(e["question_unit_id"]), views.get(e["answer_unit_id"])
                    if q and a and a.speaker_label and guides.name_matches(w["name"], a.speaker_label or ""):
                        notable.append({"hearing_id": h["id"], "hearing_date": h["hearing_date"], **e,
                                        "question": _brackets(q.text[:600]), "answer": _brackets(a.text[:600]),
                                        "question_speaker": q.speaker_label, "answer_speaker": a.speaker_label})
        hearings.append({"id": h["id"], "hearing_date": h["hearing_date"], "digest_sentences": sents})
    wcases = _witness_cases(cases, [w]).get(slug, [])
    return {"slug": slug, "requested_slug": requested, "aliases": w.get("aliases", []),
            "name": w["name"], "label": w["label"], "artifact_id": g["artifact_id"] if g else None,
            "blocks": g["blocks"] if g else [], "cases": sorted(wcases, key=lambda k: CASE_ORDER.get(k, 9)),
            "hearings": hearings, "appearances": w["appearances"], "side": w.get("side"),
            "notable_exchanges": notable[:12], "citations": list(citations.values())}


def timeline(conn: Connection) -> dict:
    cases = published_guides(conn, "case")
    ws = all_witnesses(conn)
    wcases = _witness_cases(cases, ws)
    events: list[dict] = []
    cits: dict[str, dict] = {}
    for c in cases:
        cmap = {x["source_unit_id"]: x for x in c["citations"]}
        for i, it in enumerate(block(c, "events")):
            if not it.get("date"):
                continue
            events.append({"id": f"ev_{c['key']}_{i}", "track": "story", "date": it["date"],
                           "date_precision": it.get("date_precision") or "day", "title": it.get("label") or it["text"][:60],
                           "text": it["text"], "case_keys": [c["key"]], "kind": "indictment_fact",
                           "link": {"type": "case", "key": c["key"]}, "citation_ids": it["citation_ids"]})
            for cid in it["citation_ids"]:
                if cid in cmap:
                    cits[cid] = cmap[cid]
    person_of = slug_by_raw(ws)
    slug_of = {raw: w["slug"] for raw, w in person_of.items()}

    def names_of(raws: list[str]) -> list[str]:
        out: list[str] = []
        for x in raws:
            n = person_of[x]["name"] if x in person_of else guides.witness_name(x)[0]
            if n not in out:
                out.append(n)
        return out

    for h in public_hearings(conn):
        names = names_of(h["witnesses"] or [])
        keys = sorted({k for x in (h["witnesses"] or []) for k in wcases.get(slug_of.get(x, ""), [])},
                      key=lambda k: CASE_ORDER.get(k, 9))
        d = _hearing_digest(conn, h["id"]) if h["has_digest"] else None
        events.append({"id": h["id"], "track": "trial", "date": h["hearing_date"], "date_precision": "day",
                       "title": ("דיון: עדות " + ", ".join(names)) if names else "דיון",
                       "text": d["summary_sentences"][0]["text"] if d and d["summary_sentences"] else None,
                       "case_keys": keys, "kind": "hearing", "link": {"type": "hearing", "id": h["id"]}, "citation_ids": []})
    from ..guide_service import published_hearing_days

    by_date = {e["date"]: e for e in events if e["kind"] == "hearing"}
    day_docs: set[str] = set()
    for d in published_hearing_days(conn):
        day_docs.add(d["source_version_id"])
        names = [person_of[w["name"]]["name"] if w["name"] in person_of else guides.witness_name(w["name"])[0]
                 for w in d["witnesses"]]
        side_he = {"defense": "עד/ת הגנה", "prosecution": "עד/ת תביעה"}
        who = ", ".join(f"{n} ({side_he[w['side']]})" if w.get("side") in side_he else n
                        for n, w in zip(names, d["witnesses"], strict=False))
        keys = sorted({k for w in d["witnesses"] for k in wcases.get(slug_of.get(w["name"], ""), [])},
                      key=lambda k: CASE_ORDER.get(k, 9))
        known = by_date.get(d["hearing_date"])
        if known is not None:  # the hearing has a transcript: the notice only adds who testified
            known.setdefault("notice_witnesses", []).extend(names)
            continue
        text = "לפי הודעת בית המשפט" + (f". הדיון הבא נקבע ל־{d['next_hearing_date']}" if d.get("next_hearing_date") else "")
        events.append({"id": f"hd_{d['source_version_id']}_{d['hearing_date']}", "track": "trial", "date": d["hearing_date"],
                       "date_precision": "day", "title": ("יום דיון: עדות " + who) if who else "יום דיון",
                       "text": text, "case_keys": keys, "kind": "hearing_day", "significance": "substantive",
                       "link": {"type": "document", "id": d["source_version_id"]}, "citation_ids": []})
    for e in events:
        e.setdefault("significance", "substantive")
    for doc in public_documents(conn, source_type=None, limit=1000, offset=0):
        if not doc["document_date"] or doc["source_version_id"] in day_docs:
            continue
        events.append({"id": doc["source_version_id"], "track": "trial", "date": doc["document_date"][:10],
                       "date_precision": "day", "title": doc["display_title"],
                       "text": doc["brief"]["summary"] if doc["brief"] else None, "case_keys": [],
                       "kind": doc["source_type"], "significance": doc["significance"] or "substantive",
                       "link": {"type": "document", "id": doc["source_version_id"]}, "citation_ids": []})
    events.sort(key=lambda e: (e["date"], e["track"]))
    return {"events": events, "citations": cits,
            "range": {"from": events[0]["date"] if events else None, "to": events[-1]["date"] if events else None}}
