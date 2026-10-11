"""What a mirror (the WordPress site) needs to keep its own copy of the public content (11.10.2026).

* ``objects`` — ids of everything public, so the mirror can fill itself;
* ``changes(since)`` — what changed after a moment, from publications, source publication state and the audit log,
  so the mirror refreshes only those objects (webhooks do the same in real time; this catches missed ones).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.engine import Connection

from .core import rows, scalar
from .ops import current_corpus_version


def objects(conn: Connection) -> dict[str, Any]:
    from .. import guide_service

    hearings = rows(conn, """SELECT h.id, sv.page_count FROM ntk.hearings h
                             JOIN ntk.source_versions sv ON sv.id = h.source_version_id
                             WHERE sv.publication_state = 'published' ORDER BY h.hearing_date""")
    docs = rows(conn, """SELECT sv.id, sv.page_count, d.source_type::text AS source_type FROM ntk.source_versions sv
                         JOIN ntk.source_documents d ON d.id = sv.document_id
                         WHERE sv.publication_state = 'published' AND d.source_type <> 'protocol'
                           AND NOT EXISTS (SELECT 1 FROM ntk.hearings h WHERE h.source_version_id = sv.id)""")
    guides = rows(conn, """SELECT DISTINCT ga.object_type, ga.object_id FROM ntk.generated_artifacts ga
                           JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
                           WHERE ga.artifact_type = 'guide'""")
    claims = rows(conn, """SELECT DISTINCT ga.object_id FROM ntk.generated_artifacts ga
                           JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
                           WHERE ga.artifact_type = 'claim_card'""")
    return {
        "corpus_version": current_corpus_version(conn),
        "hearings": [{"id": h["id"], "page_count": h["page_count"]} for h in hearings],
        "documents": [{"id": d["id"], "page_count": d["page_count"], "source_type": d["source_type"]} for d in docs],
        "cases": sorted(g["object_id"] for g in guides if g["object_type"] == "case"),
        "witnesses": [w["slug"] for w in guide_service.witnesses(conn)],
        "claims": [c["object_id"] for c in claims],
        "document_types": sorted({d["source_type"] for d in docs}),
    }


def changes(conn: Connection, since: dt.datetime) -> dict[str, Any]:
    hearings: set[str] = set()
    documents: set[str] = set()
    guides: set[str] = set()
    claims: set[str] = set()
    for r in rows(conn, """
        SELECT ga.object_type, ga.object_id, ga.artifact_type FROM ntk.publications p
        JOIN ntk.generated_artifacts ga ON ga.id = p.artifact_id
        WHERE p.published_at > :t OR p.unpublished_at > :t""", {"t": since}):
        if r["artifact_type"] == "guide":
            guides.add(f"{r['object_type']}:{r['object_id']}")
        elif r["artifact_type"] == "claim_card":
            claims.add(r["object_id"])
        elif r["object_type"] == "hearing":
            hearings.add(r["object_id"])
        elif r["object_type"] == "document":
            documents.add(r["object_id"])
    svs = {r["id"] for r in rows(conn, "SELECT id FROM ntk.source_versions WHERE publication_changed_at > :t", {"t": since})}
    svs |= {r["object_id"] for r in rows(conn, """SELECT DISTINCT object_id FROM ntk.audit_events
                                                  WHERE occurred_at > :t AND object_type = 'source_version'""", {"t": since})}
    for sv in svs:
        hid = scalar(conn, "SELECT id FROM ntk.hearings WHERE source_version_id = :sv", {"sv": sv})
        (hearings if hid else documents).add(hid or sv)
    for r in rows(conn, """SELECT details->>'hearing_id' AS h, object_id FROM ntk.audit_events
                           WHERE occurred_at > :t AND action = 'hearing.demoted_to_document'""", {"t": since}):
        hearings.add(r["h"])
        documents.add(r["object_id"])
    any_change = bool(hearings or documents or guides or claims) or bool(scalar(
        conn, "SELECT count(*) FROM ntk.audit_events WHERE occurred_at > :t AND object_type <> 'answer'", {"t": since}))
    return {"since": since.isoformat(), "now": dt.datetime.now(dt.UTC).isoformat(),
            "corpus_version": current_corpus_version(conn), "lists_changed": any_change,
            "hearings": sorted(hearings), "documents": sorted(documents), "guides": sorted(guides), "claims": sorted(claims)}
