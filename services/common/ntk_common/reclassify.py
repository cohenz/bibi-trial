"""Documents that were taken for hearing protocols but are not (11.10.2026).

A protocol records a hearing: it has an attendance list ("נוכחים") or speaker turns. A one-page court decision or
notice that merely mentions a protocol ("פרוטוקול הדיון מיום … הוקלט") is a document, not a hearing. Two entry points:

* ``is_hearing_record(units)`` — used by the pipeline right after parsing, so such a file never becomes a hearing;
* ``demote(conn, …)`` — turns an existing false hearing back into a document: the hearing row goes, its units and
  chunks stay (citations keep resolving), its summary is withdrawn, the document gets its proper type and title.
"""

from __future__ import annotations

import re

from .db.core import execute, j, row, rows, scalar

SPEECH_TYPES = {"speech_turn", "question", "answer"}
_DECISION = re.compile(r"החלט|הכרעת\s*דין|גזר\s*דין|פסק\s*דין")
_NOTICE = re.compile(r"הודע")


def is_hearing_record(unit_types: list[str], text: str) -> bool:
    return bool(SPEECH_TYPES & set(unit_types)) or "נוכחים" in (text or "")[:4000]


def guess_kind(text: str, filename: str = "") -> str:
    from .inbox import filename_meta

    label = filename_meta(filename).get("type_label") or ""
    if "החלטה" in label:
        return "decision"
    if "הודעה" in label:
        return "notice"
    head = (text or "")[:1500]
    if _DECISION.search(head):
        return "decision"
    if _NOTICE.search(head):
        return "notice"
    return "decision"


def new_title(kind: str, original_filename: str, date: str | None) -> str:
    from .inbox import _title

    return _title({"doc_kind": kind, "object_key": original_filename or ""}, {"document_date": date, "title": None})


def candidates(conn) -> list[dict]:
    """Hearings whose protocol has no speaker turns and no attendance list."""
    out = []
    for h in rows(conn, """SELECT h.id, h.hearing_date::text AS hearing_date, h.source_version_id, sv.metadata,
                                  d.id AS document_id
                           FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
                           JOIN ntk.source_documents d ON d.id = sv.document_id WHERE d.source_type = 'protocol'"""):
        us = rows(conn, """SELECT unit_type, raw_text FROM ntk.source_units WHERE source_version_id = :sv
                           AND superseded_at IS NULL ORDER BY unit_ordinal""", {"sv": h["source_version_id"]})
        text = "\n".join(u["raw_text"] or "" for u in us)
        if not is_hearing_record([u["unit_type"] for u in us], text):
            h["kind"] = guess_kind(text, (h["metadata"] or {}).get("original_filename") or "")
            h["units"] = len(us)
            h["text"] = text[:300]
            out.append(h)
    return out


def demote(conn, *, hearing_id: str, kind: str, actor: str) -> dict:
    from .db import ops

    h = row(conn, """SELECT h.id, h.hearing_date::text AS hearing_date, h.source_version_id, sv.metadata, sv.document_id
                     FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id WHERE h.id = :h""",
            {"h": hearing_id})
    if h is None:
        return {"hearing_id": hearing_id, "demoted": False, "reason": "not_found"}
    if scalar(conn, "SELECT count(*) FROM ntk.qa_exchanges WHERE hearing_id = :h", {"h": hearing_id}):
        return {"hearing_id": hearing_id, "demoted": False, "reason": "has question/answer pairs"}
    svid = h["source_version_id"]
    meta = h["metadata"] or {}
    # withdraw the hearing summary (it summarised a document as if it were a hearing)
    arts = rows(conn, """SELECT id::text AS id FROM ntk.generated_artifacts WHERE object_type = 'hearing' AND object_id = :h""",
                {"h": hearing_id})
    for a in arts:
        execute(conn, "UPDATE ntk.publications SET unpublished_at = now() WHERE artifact_id = CAST(:a AS uuid) AND unpublished_at IS NULL",
                {"a": a["id"]})
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded', updated_at = now() WHERE id = CAST(:a AS uuid)",
                {"a": a["id"]})
        execute(conn, """UPDATE ntk.review_tasks SET status = 'cancelled', decided_by = :by, updated_at = now(), completed_at = now()
                         WHERE object_type = 'artifact' AND object_id = :a AND status = 'open'""", {"a": a["id"], "by": actor})
    court = kind == "decision"
    execute(conn, """UPDATE ntk.source_units SET hearing_id = NULL,
                         unit_type = CASE WHEN :court AND unit_type IN ('other', 'caption') THEN 'decision' ELSE unit_type END,
                         speaker_label = CASE WHEN :court AND speaker_label IS NULL THEN 'בית המשפט' ELSE speaker_label END,
                         speaker_role = CASE WHEN :court AND speaker_role IS NULL THEN 'court' ELSE speaker_role END
                     WHERE source_version_id = :sv""", {"sv": svid, "court": court})
    execute(conn, "UPDATE ntk.retrieval_chunks SET hearing_id = NULL WHERE source_version_id = :sv", {"sv": svid})
    execute(conn, "DELETE FROM ntk.hearing_roles WHERE hearing_id = :h", {"h": hearing_id})
    execute(conn, "DELETE FROM ntk.hearings WHERE id = :h", {"h": hearing_id})
    date = meta.get("document_date") or h["hearing_date"]
    title = new_title(kind, meta.get("name_from") or meta.get("original_filename") or "", date)
    execute(conn, "UPDATE ntk.source_documents SET source_type = CAST(:t AS ntk.source_type), canonical_title = :ti WHERE id = :d",
            {"t": kind, "ti": title, "d": h["document_id"]})
    execute(conn, "UPDATE ntk.source_versions SET metadata = metadata || CAST(:p AS jsonb) WHERE id = :sv",
            {"sv": svid, "p": j({"document_date": date, "reclassified_from": "protocol", "former_hearing_id": hearing_id})})
    execute(conn, "UPDATE ntk.inbox_items SET doc_kind = :k, updated_at = now() WHERE source_key IS NOT NULL AND content_sha256 = "
                  "(SELECT content_sha256 FROM ntk.source_versions WHERE id = :sv)", {"k": kind, "sv": svid})
    ops.audit(conn, actor=actor, action="hearing.demoted_to_document", object_type="source_version", object_id=svid,
              details={"hearing_id": hearing_id, "kind": kind, "title": title, "date": date,
                       "withdrawn_artifacts": [a["id"] for a in arts]})
    ops.enqueue_webhook(conn, "source_version.published", {"source_version_id": svid, "reclassified": kind})
    return {"hearing_id": hearing_id, "demoted": True, "source_version_id": svid, "kind": kind, "title": title, "date": date}
