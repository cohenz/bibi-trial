"""Object-store inbox: bulk and daily intake of court-file documents.

People drop PDFs (any folder structure) under ``NTK_INBOX_PREFIX`` (default
``inbox/``) in the sources bucket. A scan:

1. lists the prefix and registers every new object (key + ETag) in
   ``ntk.inbox_items``;
2. classifies each new item from its first two pages and last page: rules
   first (headings such as "פרוטוקול", "החלטה", "בקשה"), the model only when the
   rules are unsure; reads the case number(s) and the document/hearing date;
3. marks exact duplicates (same SHA-256 as an ingested source or as another
   inbox item) and documents of another case, and copies everything else to
   the immutable content-addressed key ``sources/sha256/…``;
4. when processing is on, turns classified items into ordinary ingestion jobs.

Nothing in the inbox is ever deleted or modified by the system. Publication of
sources follows the operator's policy (``auto_publish_source``): protocols and
decisions whose own pages carry this case's number; AI layers are never
published automatically.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from . import ids
from .db.core import execute, j, row, rows, scalar

KINDS = ("protocol", "decision", "motion", "response", "notice", "affidavit", "indictment", "exhibit", "other")
KIND_HE = {
    "protocol": "פרוטוקול דיון", "decision": "החלטה", "motion": "בקשה", "response": "תגובה", "notice": "הודעה",
    "affidavit": "תצהיר", "indictment": "כתב אישום", "exhibit": "מוצג", "other": "מסמך",
}
AUTO_PUBLISH_KINDS = {"protocol", "decision", "motion", "response", "notice"}
MODEL_THRESHOLD = 0.7
CLASSIFIER_VERSION = "inbox-classifier-1"

_CASE_RE = re.compile(r"(?<!\d)(\d{4,6})\s*[-–]\s*(\d{2})\s*[-–]\s*(\d{2})(?!\d)")
_PUNCT = re.compile(r"^[\s\"'״׳:.\-–()\[\]]+")

# headings of documents the court issues outside a hearing ("העתק החלטת בית משפט", "הודעת בית המשפט")
_COURT_DOC_HEADINGS = ("העתק החלטת", "העתק החלטה", "החלטה", "החלטת", "הודעת בית המשפט", "הודעה לצדדים", "הודעה מטעם בית")
# speaker turns as printed in protocols: "כב' השופטת …:", "עו"ד חדד:", "ש.", "ת:", "העד:"
_TURN_RE = re.compile(r"^(?:[שת][.:]|(?:כב\W?\s*ה?שופט|ה?שופט(?:ת)?\s|אב\W?ד|עו\W?ד\s|ב\W?כ\s|העד(?:ה)?\b|ה?נאשם\s?\d?)[^:\n]{0,45}:)")

# heading keyword → kind, checked against the start of short lines on the first page, in this priority order
_HEADINGS: list[tuple[str, tuple[str, ...]]] = [
    ("indictment", ("כתב אישום", "כתב-אישום", "כתב האישום המתוקן", "כתב אישום מתוקן")),
    ("decision", ("הכרעת דין", "הכרעת-דין", "גזר דין", "גזר-דין", "פסק דין", "פסק-דין", "העתק החלטת", "העתק החלטה",
                  "החלטה", "החלטת")),
    ("affidavit", ("תצהיר", "הצהרה", "הצהרת")),
    ("response", ("תגובה", "תגובת", "תשובה", "תשובת", "תגובה לבקשה", "השלמת טיעון")),
    ("motion", ("בקשה", "בקשת", "בקשה דחופה")),
    ("notice", ("הודעה", "הודעת", "הודעה מעדכנת", "עדכון", "הודעה ובקשה")),
]


@dataclass
class Classification:
    source_type: str
    confidence: float
    title: str | None = None
    document_date: str | None = None
    hearing_date: str | None = None
    case_numbers: list[str] = field(default_factory=list)
    case_found: bool | None = None  # None: no case number printed at all
    method: str = "rules"
    signals: list[str] = field(default_factory=list)
    text_chars: int = 0
    page_count: int = 0
    model_run_id: str | None = None
    fingerprint: list[int] = field(default_factory=list)  # text sketch of pages 1, 2 and last (inbox_dupes)

    def to_json(self) -> dict:
        return {**asdict(self), "classifier_version": CLASSIFIER_VERSION}


def _norm_line(text: str) -> str:
    return _PUNCT.sub("", text or "").strip()


def case_numbers_in(text: str) -> list[str]:
    seen: list[str] = []
    for m in _CASE_RE.finditer(text or ""):
        n = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if n not in seen:
            seen.append(n)
    return seen


def classify_by_rules(first_pages: str, last_page: str = "", filename: str = "", *,
                      case_number: str | None = None) -> Classification:
    from .pipeline.protocol import parse_date

    lines = [ln for ln in (first_pages or "").splitlines() if ln.strip()]
    head = lines[:60]
    head_text = "\n".join(head)
    signals: list[str] = []
    kind, conf, title = "other", 0.3, None

    # A protocol records a hearing: an attendance list ("נוכחים") or a "פרוטוקול" heading with speaker turns. A mere
    # mention ("פרוטוקול הדיון מיום … הוקלט" in a decision) is not enough: court decisions and notices issued outside a
    # hearing often refer to a protocol.
    norm = [_norm_line(ln) for ln in head]
    protocol_heading = any(t.startswith("פרוטוקול") and len(t.split()) <= 6 for t in norm)
    present = "נוכחים" in head_text or "נוכחות:" in head_text
    turns = sum(1 for ln in lines[:200] if _TURN_RE.match(_norm_line(ln)))
    if present or (protocol_heading and turns >= 2):
        kind, conf, title = "protocol", 0.95, "פרוטוקול דיון"
        signals.append("protocol:" + ("attendance" if present else "") + (f"+turns:{turns}" if turns else ""))
    elif protocol_heading and not any(t.startswith(_COURT_DOC_HEADINGS) for t in norm[:20]):
        kind, conf, title = "protocol", 0.7, "פרוטוקול דיון"
        signals.append("heading:פרוטוקול")
    else:
        for ln in head:
            t = _norm_line(ln)
            if not t or len(t.split()) > 12:
                continue
            hit = next(((k, kw) for k, kws in _HEADINGS for kw in kws if t.startswith(kw)), None)
            if hit:
                kind, kw = hit
                conf = 0.9 if len(t.split()) <= 8 else 0.75
                title = t[:120]
                signals.append(f"heading:{kw}")
                break
    # documents of one or two pages end on the pages already read as "first pages"
    tail = last_page if (last_page or "").strip() else "\n".join(lines[-25:])
    if kind in {"other", "decision"} and any(k in tail for k in ("ניתנה היום", "ניתן היום", "ניתנה בהעדר", "ניתנה במעמד")):
        signals.append("tail:ניתנה היום")
        if kind == "other":
            kind, conf, title = "decision", 0.75, title or "החלטה"
        else:
            conf = max(conf, 0.95)
    if kind == "other" and filename:
        fn = filename.rsplit("/", 1)[-1]
        for k, kws in [("protocol", ("פרוטוקול", "protocol")), ("decision", ("החלטה", "decision")), ("motion", ("בקשה",))]:
            if any(x in fn.lower() for x in kws):
                kind, conf = k, 0.55
                signals.append(f"filename:{k}")
                break

    nums = case_numbers_in(head_text + "\n" + tail)
    found = (case_number in nums) if (case_number and nums) else (None if not nums else False)
    hearing_date = None
    document_date = None
    if kind == "protocol":
        hearing_date = parse_date(head_text)
        document_date = hearing_date
    else:
        for ln in reversed(tail.splitlines()):
            if "ניתנ" in ln or "היום" in ln:
                document_date = parse_date(ln)
                if document_date:
                    break
        document_date = document_date or parse_date(head_text) or parse_date(tail)
    return Classification(kind, conf, title, document_date, hearing_date, nums, found, "rules", signals,
                          len(first_pages or "") + len(tail))


def _page_text(pages) -> str:
    return "\n".join(ln.text for p in pages for ln in p.lines if ln.kind != "footer")


def extract_for_classification(data: bytes, *, ocr: bool, ocr_langs: str) -> tuple[str, str, int, list[str]]:
    """Text of pages 1–2 and of the last page, OCR'd when there is no text layer."""
    from .pipeline import pdf as pdfmod

    notes: list[str] = []
    pages = pdfmod.extract_text_layer(data, only_pages={1, 2, -1})
    import io

    import pypdf

    total = len(pypdf.PdfReader(io.BytesIO(data), strict=False).pages)
    if ocr and pdfmod.tesseract_available(ocr_langs):
        for i, p in enumerate(pages):
            if p.method == "empty":
                pages[i] = pdfmod.ocr_page(data, p.page, ocr_langs)
                notes.append(f"ocr:page{p.page}")
    elif any(p.method == "empty" for p in pages):
        notes.append("no_text_layer")
    first = [p for p in pages if p.page <= 2]
    last = [p for p in pages if p.page == total and p.page > 2]
    return _page_text(first), _page_text(last), total, notes


def classify_document(data: bytes, *, filename: str, settings, runner=None, corpus_version: str = "cv-inbox") -> Classification:
    first, last, total, notes = extract_for_classification(data, ocr=settings.ocr_enabled, ocr_langs=settings.ocr_langs)
    from .inbox_dupes import fingerprint

    c = classify_by_rules(first, last, filename, case_number=settings.court_case_number)
    c.page_count = total
    c.fingerprint = fingerprint(first + "\n" + last)
    c.signals += notes
    if runner is not None and c.confidence < MODEL_THRESHOLD and (first or last):
        run = runner.run("classify_document", {"filename": filename.rsplit("/", 1)[-1], "page_count": total,
                                               "first_pages": first[:6000], "last_page": last[:3000]},
                         input_source_ids=[], corpus_version=corpus_version)
        c.model_run_id = run.id
        if run.ok:
            out = run.output
            c.signals.append(f"model:{out['source_type']}@{out['confidence']}")
            if out["confidence"] >= 0.6 and out["source_type"] in KINDS:
                c.source_type, c.confidence, c.method = out["source_type"], float(out["confidence"]), "model"
                c.title = out.get("title") or c.title
                c.document_date = out.get("document_date") or c.document_date
                c.hearing_date = out.get("hearing_date") or c.hearing_date
                for n in out.get("court_case_numbers") or []:
                    if n not in c.case_numbers:
                        c.case_numbers.append(n)
                if c.case_numbers:
                    c.case_found = settings.court_case_number in c.case_numbers
        else:
            c.signals.append("model:failed")
    return c


# ---------------------------------------------------------------------------
# persistence + scan
# ---------------------------------------------------------------------------
def register_objects(conn, objects, *, scan_id: str) -> int:
    n = 0
    for o in objects:
        n += execute(conn, """INSERT INTO ntk.inbox_items (id, object_key, etag, size_bytes, last_modified, scan_id)
                              VALUES (CAST(:id AS uuid), :k, :e, :s, CAST(:lm AS timestamptz), CAST(:scan AS uuid))
                              ON CONFLICT (object_key, etag) DO NOTHING""",
                     {"id": str(ids.derived_uuid("inbox_item", o.key, o.etag)), "k": o.key, "e": o.etag or "",
                      "s": o.size, "lm": o.last_modified, "scan": scan_id})
    return n


def _set(conn, item_id: str, **fields: Any) -> None:
    cols = []
    params: dict[str, Any] = {"id": item_id}
    for k, v in fields.items():
        if k in {"classification", "error"}:
            cols.append(f"{k} = CAST(:{k} AS jsonb)")
            params[k] = j(v) if v is not None else None
        elif k == "job_id":
            cols.append("job_id = CAST(:job_id AS uuid)")
            params[k] = v
        else:
            cols.append(f"{k} = :{k}")
            params[k] = v
    execute(conn, f"UPDATE ntk.inbox_items SET {', '.join(cols)}, updated_at = now() WHERE id = CAST(:id AS uuid)", params)


def start_scan(engine, *, trigger: str) -> str:
    sid = str(ids.derived_uuid("inbox_scan", trigger, dt.datetime.now(dt.UTC).isoformat()))
    with engine.begin() as conn:
        execute(conn, "INSERT INTO ntk.inbox_scans (id, trigger) VALUES (CAST(:id AS uuid), :t)", {"id": sid, "t": trigger})
    return sid


def finish_scan(engine, scan_id: str, *, stats: dict, error: dict | None = None) -> None:
    with engine.begin() as conn:
        execute(conn, """UPDATE ntk.inbox_scans SET finished_at = now(), stats = CAST(:s AS jsonb), error = CAST(:e AS jsonb)
                         WHERE id = CAST(:id AS uuid)""", {"id": scan_id, "s": j(stats), "e": j(error) if error else None})


def list_new(services, *, prefix: str, scan_id: str) -> dict:
    objects = services.storage.list(prefix)
    with services.engine.begin() as conn:
        new = register_objects(conn, objects, scan_id=scan_id)
        pending = [str(r["id"]) for r in rows(conn, "SELECT id FROM ntk.inbox_items WHERE status = 'discovered' ORDER BY object_key")]
    return {"listed": len(objects), "new": new, "pending_ids": pending}


def classify_item(services, item_id: str) -> str:
    """Classify one discovered item. Returns its new status."""
    s = services.settings
    with services.engine.connect() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": item_id})
    if it is None or it["status"] != "discovered":
        return (it or {}).get("status", "missing")
    key = it["object_key"]
    try:
        if it["size_bytes"] > s.max_upload_bytes:
            with services.engine.begin() as conn:
                _set(conn, item_id, status="unsupported", error={"code": "file_too_large", "size": it["size_bytes"]})
            return "unsupported"
        data = services.storage.get_bytes(key, max_bytes=s.max_upload_bytes)
        sha = ids.sha256_bytes(data)
        if not data[:1024].lstrip().startswith(b"%PDF-"):
            with services.engine.begin() as conn:
                _set(conn, item_id, status="unsupported", content_sha256=sha,
                     error={"code": "not_a_pdf", "extension": key.rsplit(".", 1)[-1].lower() if "." in key else ""})
            return "unsupported"
        # claim the hash under a lock so two copies classified at the same time cannot both pass as originals
        with services.engine.begin() as conn:
            execute(conn, "SELECT pg_advisory_xact_lock(hashtextextended(:s, 0))", {"s": sha})
            dup_sv = scalar(conn, "SELECT id FROM ntk.source_versions WHERE content_sha256 = :s ORDER BY id LIMIT 1", {"s": sha})
            dup_item = scalar(conn, """SELECT id::text FROM ntk.inbox_items WHERE content_sha256 = :s AND id <> CAST(:id AS uuid)
                                         AND status NOT IN ('duplicate', 'failed', 'removed') ORDER BY first_seen_at LIMIT 1""",
                              {"s": sha, "id": item_id})
            if dup_sv or dup_item:
                _set(conn, item_id, status="duplicate", content_sha256=sha, duplicate_of=dup_sv or f"inbox:{dup_item}")
            else:
                _set(conn, item_id, content_sha256=sha)
        if dup_sv or dup_item:
            if s.inbox_delete_duplicates:
                from .inbox_dupes import remove_copy

                res = remove_copy(services, item_id, actor="inbox:auto", reason="exact duplicate (same SHA-256)")
                return "removed" if res.get("removed") else "duplicate"
            return "duplicate"
        c = classify_document(data, filename=key, settings=s, runner=services.runner)
        from .inbox_dupes import find_possible_duplicate

        with services.engine.begin() as conn:
            maybe = find_possible_duplicate(conn, fp=c.fingerprint, page_count=c.page_count, sha=sha, item_id=item_id,
                                            date=plausible_date(c.hearing_date or c.document_date))
            if maybe:
                # held: not copied to the write-once sources/ area and not ingested until the operator decides
                _set(conn, item_id, status="possible_duplicate", doc_kind=c.source_type, classification=c.to_json(),
                     duplicate_of=maybe[0], similarity=round(maybe[1], 3), error=None)
        if maybe:
            return "possible_duplicate"
        source_key = services.storage.content_key(sha)
        services.storage.put_bytes(source_key, data, mime_type="application/pdf")
        status = "foreign_case" if c.case_found is False else "classified"
        with services.engine.begin() as conn:
            _set(conn, item_id, status=status, content_sha256=sha, source_key=source_key, doc_kind=c.source_type,
                 classification=c.to_json(), error=None)
        return status
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
        with services.engine.begin() as conn:
            _set(conn, item_id, status="failed", error={"code": type(exc).__name__, "message": str(exc)[:500]})
        return "failed"


# File names in the operator's archive follow "NNNN — YYYY-MM-DD — <type> — <description>.pdf" (underscores stand
# for characters a file name cannot hold, e.g. "ע_י" = "ע\"י", "19_05_2021" = "19/05/2021").
_FNAME_RE = re.compile(r"^\s*(?P<num>\d{1,6})\s*[—–-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*[—–-]\s*(?P<type>[^—–]+?)\s*[—–]\s*(?P<desc>.+?)\s*$")
_GENERIC_TYPES = {"מסמך", "extra_document", "court_document", "document"}
DATE_MIN, DATE_MAX = "2016-01-01", "2035-12-31"


def filename_meta(object_key: str) -> dict:
    name = object_key.rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    m = _FNAME_RE.match(name)
    if not m:
        return {}
    desc = m.group("desc").strip()
    desc = re.sub(r"(?<=[א-ת])_(?=[א-ת])", '"', desc)            # ע_י → ע"י, עו_ד → עו"ד
    desc = re.sub(r"(?<=\d)_(?=\d)", "/", desc)                  # 19_05_2021 → 19/05/2021
    desc = desc.replace("_", " ").strip(" .")
    typ = m.group("type").strip()
    out = {"number": m.group("num"), "date": m.group("date"), "type_label": None if typ in _GENERIC_TYPES else typ}
    if desc and desc not in _GENERIC_TYPES:
        out["description"] = desc
    return out


def plausible_date(d: str | None) -> str | None:
    """Dates read by OCR or from attachments can be absurd (year 7071) or far older than the case; drop those."""
    if not d or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return None
    return d if DATE_MIN <= d <= DATE_MAX else None


def document_date_for(it: dict, c: dict) -> str | None:
    kind = it["doc_kind"] or "other"
    fm = filename_meta(it["object_key"])
    if kind == "protocol":
        return plausible_date(c.get("hearing_date")) or plausible_date(fm.get("date"))
    # the archive's own date is the filing/issue date; dates inside a document may belong to its attachments
    return plausible_date(fm.get("date")) or plausible_date(c.get("document_date"))


def _title(it: dict, c: dict) -> str:
    kind = it["doc_kind"] or "other"
    fm = filename_meta(it["object_key"])
    heading = KIND_HE["protocol"] if kind == "protocol" else (c.get("title") or KIND_HE.get(kind, "מסמך"))
    desc = fm.get("description")
    if desc:
        # the archive's description says what the document is about; the printed heading (often OCR'd) stays in metadata
        label = KIND_HE.get(kind, "מסמך")
        title = f"{label}: {desc}" if not desc.startswith(label) else desc
    else:
        date = document_date_for(it, c)
        title = f"{heading} — {date}" if date else f"{heading} — {it['object_key'].rsplit('/', 1)[-1]}"
    return title[:300]


def job_input_for(it: dict, settings) -> dict:
    c = it["classification"] or {}
    kind = it["doc_kind"] or "other"
    case_verified = c.get("case_found") is True
    return {
        "case_id": settings.case_id,
        "manifest": "inbox",
        "document": {
            "title": _title(it, c),
            "url": None,
            "canonical_key": f"inbox-sha256:{it['content_sha256']}",
            # the protocol parser reads the hearing date from the caption; the classifier's guess is only a fallback
            "hearing_date": None,
            "hearing_date_hint": document_date_for(it, c) if kind == "protocol" else None,
            "document_date": document_date_for(it, c),
            "archive_number": filename_meta(it["object_key"]).get("number"),
            "source_type": kind,
            "authority_tier": 1,
            "source_owner": "הרשות השופטת" if kind in {"protocol", "decision"} else "צד להליך / תיק בית המשפט",
            "court_record_status": "filed",
            "original_filename": it["object_key"],
        },
        "source": {"s3_key": it["source_key"], "expected_sha256": it["content_sha256"]},
        "claim_ids": [],
        "auto_publish_source": kind in AUTO_PUBLISH_KINDS and case_verified,
        "case_number_verified": case_verified,
        "inbox_item_id": str(it["id"]),
    }


def queue_items(services, queue, *, task_name: str, kinds: list[str] | None = None, limit: int = 5000,
                item_ids: list[str] | None = None, requested_by: str = "inbox") -> dict:
    """Create ingestion jobs for classified items (optionally only some kinds or ids)."""
    from .db import ops
    from .orchestrator import job_idempotency_key

    with services.engine.connect() as conn:
        items = rows(conn, """SELECT * FROM ntk.inbox_items WHERE status = 'classified'
                              AND (CAST(:kinds AS text[]) IS NULL OR doc_kind = ANY(:kinds))
                              AND (CAST(:ids AS uuid[]) IS NULL OR id = ANY(CAST(:ids AS uuid[])))
                              ORDER BY (classification->>'document_date') NULLS LAST, object_key LIMIT :lim""",
                     {"kinds": kinds, "ids": item_ids, "lim": limit})
    created = 0
    for it in items:
        inp = job_input_for(it, services.settings)
        with services.engine.begin() as conn:
            job, new = ops.create_job(conn, idempotency_key=job_idempotency_key(inp), input_=inp, requested_by=requested_by)
            _set(conn, str(it["id"]), status="queued", job_id=str(job["id"]))
        if new:
            queue.enqueue(task_name, str(job["id"]))
            created += 1
    return {"queued": len(items), "jobs_created": created}


def sync_job_status(conn, job_id: str, status: str) -> None:
    new = {"succeeded": "ingested", "failed": "ingest_failed"}.get(status)
    if new:
        execute(conn, """UPDATE ntk.inbox_items SET status = :s, updated_at = now()
                         WHERE job_id = CAST(:j AS uuid) AND status IN ('queued', 'ingest_failed', 'ingested')""",
                {"s": new, "j": job_id})
    if new == "ingested":
        from .inbox_dupes import apply_best_name

        for r in rows(conn, "SELECT DISTINCT content_sha256 AS s FROM ntk.inbox_items WHERE job_id = CAST(:j AS uuid)",
                      {"j": job_id}):
            if r["s"]:
                apply_best_name(conn, r["s"])


def summary(conn) -> dict:
    by = rows(conn, """SELECT status, coalesce(doc_kind, '') AS kind, count(*) AS n, sum(size_bytes) AS bytes,
                              sum(coalesce((classification->>'page_count')::int, 0)) AS pages
                       FROM ntk.inbox_items GROUP BY 1, 2 ORDER BY 1, 2""")
    totals = {"items": sum(r["n"] for r in by), "bytes": int(sum(r["bytes"] or 0 for r in by)),
              "pages": int(sum(r["pages"] or 0 for r in by))}
    status: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for r in by:
        status[r["status"]] = status.get(r["status"], 0) + r["n"]
        if r["kind"]:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["n"]
    low = scalar(conn, """SELECT count(*) FROM ntk.inbox_items WHERE status = 'classified'
                          AND (classification->>'confidence')::float < :t""", {"t": MODEL_THRESHOLD})
    no_case = scalar(conn, """SELECT count(*) FROM ntk.inbox_items WHERE status = 'classified'
                              AND classification->'case_found' = 'null'::jsonb""")
    scans = rows(conn, "SELECT * FROM ntk.inbox_scans ORDER BY started_at DESC LIMIT 5")
    return {"totals": totals, "by_status": status, "by_kind": kinds, "matrix": by,
            "low_confidence": low, "case_number_not_printed": no_case, "recent_scans": scans}
