"""L0 persistence: cases, documents, source versions, hearings, units,
exchanges, chunks. All writes are idempotent (ON CONFLICT DO NOTHING on
deterministic ids); re-running the same pipeline produces no new rows."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from .. import hebrew, ids
from ..pipeline import L0Result
from ..pipeline.chunking import ChunkRecord
from ..pipeline.qa import Exchange
from .core import execute, j, row, rows, scalar, vector_literal


def ensure_case(conn: Connection, *, case_id: str, court_case_number: str, title: str, court_name: str) -> None:
    execute(conn, """
        INSERT INTO ntk.cases (id, court_case_number, title, court_name)
        VALUES (:id, :num, :title, :court) ON CONFLICT (id) DO NOTHING
    """, {"id": case_id, "num": court_case_number, "title": title, "court": court_name})


def ensure_document(conn: Connection, *, document_id: str, case_id: str, title: str, source_type: str,
                    authority_tier: int, source_owner: str, source_stance: str | None, canonical_url: str | None,
                    default_court_record_status: str = "unknown", legal_access_notes: str | None = None,
                    metadata: dict | None = None) -> None:
    execute(conn, """
        INSERT INTO ntk.source_documents (id, case_id, canonical_title, source_type, authority_tier, source_owner,
            source_stance, canonical_url, legal_access_notes, default_court_record_status, metadata)
        VALUES (:id, :case_id, :title, CAST(:stype AS ntk.source_type), :tier, :owner, :stance, :url, :notes,
            CAST(:crs AS ntk.court_record_status), CAST(:meta AS jsonb))
        ON CONFLICT (id) DO NOTHING
    """, {"id": document_id, "case_id": case_id, "title": title, "stype": source_type, "tier": authority_tier,
          "owner": source_owner, "stance": source_stance, "url": canonical_url, "notes": legal_access_notes,
          "crs": default_court_record_status, "meta": j(metadata or {})})


def find_version(conn: Connection, source_version_id: str) -> dict | None:
    return row(conn, "SELECT * FROM ntk.source_versions WHERE id = :id", {"id": source_version_id})


def latest_version_of(conn: Connection, document_id: str) -> dict | None:
    return row(conn, """SELECT * FROM ntk.source_versions WHERE document_id = :d ORDER BY retrieved_at DESC, id LIMIT 1""",
               {"d": document_id})


def insert_source_version(conn: Connection, *, document_id: str, content_sha256: str, retrieved_at: Any,
                          mime_type: str, size_bytes: int, object_uri: str | None, source_url: str | None,
                          s3: dict | None, page_count: int | None, parser_version: str | None,
                          extractor_version: str | None, court_record_status: str, published_at: Any = None,
                          metadata: dict | None = None) -> tuple[str, bool]:
    """Returns (source_version_id, created). A new SHA for the same document
    supersedes the previous latest version (spec §23.2)."""
    svid = ids.source_version_id(document_id, content_sha256)
    existing = find_version(conn, svid)
    if existing:
        return svid, False
    prev = latest_version_of(conn, document_id)
    execute(conn, """
        INSERT INTO ntk.source_versions (id, document_id, content_sha256, retrieved_at, published_at, mime_type,
            object_uri, source_url, parser_version, page_count, supersedes_id, metadata, size_bytes, s3_bucket, s3_key,
            s3_version_id, s3_etag, extractor_version, court_record_status)
        VALUES (:id, :doc, :sha, :ret, :pub, :mime, :uri, :url, :pv, :pc, :sup, CAST(:meta AS jsonb), :size, :b, :k,
            :vid, :etag, :ev, CAST(:crs AS ntk.court_record_status))
        ON CONFLICT (id) DO NOTHING
    """, {"id": svid, "doc": document_id, "sha": content_sha256, "ret": retrieved_at, "pub": published_at,
          "mime": mime_type, "uri": object_uri, "url": source_url, "pv": parser_version, "pc": page_count,
          "sup": prev["id"] if prev else None, "meta": j(metadata or {}), "size": size_bytes,
          "b": (s3 or {}).get("bucket"), "k": (s3 or {}).get("key"), "vid": (s3 or {}).get("version_id"),
          "etag": (s3 or {}).get("etag"), "ev": extractor_version, "crs": court_record_status})
    return svid, True


def ensure_hearing(conn: Connection, *, case_id: str, hearing_date: str, source_version_id: str,
                   judges: list[str], witnesses: list[str], phase: str | None = None,
                   location: str | None = None, metadata: dict | None = None) -> str:
    hid = ids.hearing_id(case_id, hearing_date, source_version_id)
    execute(conn, """
        INSERT INTO ntk.hearings (id, case_id, hearing_date, location, phase, source_version_id, judges, witnesses, metadata)
        VALUES (:id, :case, :d, :loc, :phase, :sv, :judges, :wit, CAST(:meta AS jsonb))
        ON CONFLICT (id) DO NOTHING
    """, {"id": hid, "case": case_id, "d": hearing_date, "loc": location, "phase": phase, "sv": source_version_id,
          "judges": judges, "wit": witnesses, "meta": json.dumps(metadata or {}, ensure_ascii=False)})
    return hid


def ensure_entity(conn: Connection, *, entity_type: str, canonical_name: str, aliases: list[str] | None = None,
                  role_types: list[str] | None = None) -> str:
    eid = str(ids.derived_uuid("entity", entity_type, canonical_name))
    execute(conn, """
        INSERT INTO ntk.entities (id, entity_type, canonical_name, aliases, role_types)
        VALUES (:id, :t, :n, :a, :r)
        ON CONFLICT (entity_type, canonical_name) DO UPDATE
          SET aliases = (SELECT array_agg(DISTINCT x) FROM unnest(ntk.entities.aliases || EXCLUDED.aliases) x),
              role_types = (SELECT array_agg(DISTINCT x) FROM unnest(ntk.entities.role_types || EXCLUDED.role_types) x)
    """, {"id": eid, "t": entity_type, "n": canonical_name, "a": aliases or [], "r": role_types or []})
    return str(scalar(conn, "SELECT id FROM ntk.entities WHERE entity_type=:t AND canonical_name=:n",
                      {"t": entity_type, "n": canonical_name}))


def write_l0(conn: Connection, result: L0Result, *, hearing_id: str | None, court_record_status: str,
             speaker_entities: dict[str, str] | None = None) -> dict:
    """Persist units, exchanges and chunks for a parsed SourceVersion."""
    speaker_entities = speaker_entities or {}
    unit_rows = []
    for u in result.parsed.units:
        norm = hebrew.normalize(u.raw_text)
        unit_rows.append({
            "id": u.id, "sv": result.source_version_id, "hid": hearing_id, "ord": u.ordinal, "page": u.page,
            "ls": u.line_start, "le": u.line_end, "spk": speaker_entities.get(u.speaker_label or ""),
            "label": u.speaker_label, "phase": u.examination_phase, "utype": u.unit_type, "raw": u.raw_text,
            "norm": norm, "crs": court_record_status, "pv": result.parsed.parser_version, "tk": u.turn_key,
            "tp": u.turn_part, "role": u.speaker_role, "side": u.speaker_side, "wit": u.witness_label,
            "syn": u.synthetic_lines, "terms": hebrew.search_terms(norm), "ngr": hebrew.char_ngrams(norm)[:2000],
            "nv": hebrew.NORMALIZER_VERSION, "flags": u.flags,
        })
    n_units = execute(conn, """
        INSERT INTO ntk.source_units (id, source_version_id, hearing_id, unit_ordinal, page_no, line_start, line_end,
            speaker_entity_id, speaker_label, examination_phase, unit_type, raw_text, normalized_text,
            court_record_status, parser_version, turn_key, turn_part, speaker_role, speaker_side, witness_label,
            synthetic_lines, search_terms, char_ngrams, normalizer_version, flags)
        VALUES (:id, :sv, :hid, :ord, :page, :ls, :le, CAST(:spk AS uuid), :label, CAST(:phase AS ntk.examination_phase),
            :utype, :raw, :norm, CAST(:crs AS ntk.court_record_status), :pv, :tk, :tp, :role, :side, :wit, :syn,
            :terms, :ngr, :nv, :flags)
        ON CONFLICT (id) DO NOTHING
    """, unit_rows)
    ex_rows = [_exchange_row(e, hearing_id, result.parsed.parser_version) for e in result.exchanges] if hearing_id else []
    n_ex = execute(conn, """
        INSERT INTO ntk.qa_exchanges (id, hearing_id, question_unit_id, answer_unit_id, phase, answer_relation,
            interpreted_proposition, confidence, review_state, asker_label, asker_side, witness_label, public_wording,
            flags, rule, parser_version)
        VALUES (:id, :hid, :q, :a, CAST(:phase AS ntk.examination_phase), CAST(:rel AS ntk.answer_relation), :prop,
            :conf, 'draft', :asker, :side, :wit, :wording, :flags, :rule, :pv)
        ON CONFLICT (id) DO NOTHING
    """, ex_rows)
    n_chunks = write_chunks(conn, result.chunks, source_version_id=result.source_version_id, hearing_id=hearing_id,
                            court_record_status=court_record_status)
    return {"units_inserted": n_units, "units_total": len(unit_rows), "exchanges_inserted": n_ex,
            "exchanges_total": len(ex_rows), "chunks_inserted": n_chunks, "chunks_total": len(result.chunks)}


def _exchange_row(e: Exchange, hearing_id: str, parser_version: str) -> dict:
    return {"id": e.id, "hid": hearing_id, "q": e.question.id, "a": e.answer.id, "phase": e.phase,
            "rel": e.answer_relation, "prop": e.interpreted_proposition, "conf": e.confidence, "asker": e.asker_label,
            "side": e.asker_side, "wit": e.witness_label, "wording": e.public_wording, "flags": e.flags,
            "rule": e.rule, "pv": parser_version}


def write_chunks(conn: Connection, chunks: list[ChunkRecord], *, source_version_id: str, hearing_id: str | None,
                 court_record_status: str) -> int:
    rows_ = [{"id": c.id, "sv": source_version_id, "profile": c.chunk_profile, "tok": c.token_count, "raw": c.raw_text,
              "norm": c.normalized_text, "terms": c.prefix_forms, "ngr": c.char_ngrams, "phases": c.examination_phases,
              "spk": c.speakers, "hid": hearing_id, "crs": court_record_status} for c in chunks]
    n = execute(conn, """
        INSERT INTO ntk.retrieval_chunks (id, source_version_id, chunk_profile, token_count, raw_text, normalized_text,
            search_terms, char_ngrams, examination_phases, speakers, hearing_id, court_record_status)
        VALUES (:id, :sv, :profile, :tok, :raw, :norm, :terms, :ngr, :phases, :spk, :hid,
            CAST(:crs AS ntk.court_record_status))
        ON CONFLICT (id) DO NOTHING
    """, rows_)
    members = [{"c": c.id, "u": uid, "p": i} for c in chunks for i, uid in enumerate(c.ordered_source_unit_ids)]
    execute(conn, """
        INSERT INTO ntk.retrieval_chunk_members (chunk_id, source_unit_id, position) VALUES (:c, :u, :p)
        ON CONFLICT DO NOTHING
    """, members)
    return n


def chunks_missing_embeddings(conn: Connection, source_version_id: str, model: str) -> list[dict]:
    return rows(conn, """
        SELECT id, raw_text FROM ntk.retrieval_chunks
        WHERE source_version_id = :sv AND (embedding IS NULL OR embedding_model IS DISTINCT FROM :m)
        ORDER BY id
    """, {"sv": source_version_id, "m": model})


def set_embeddings(conn: Connection, items: list[tuple[str, list[float]]], model: str) -> int:
    return execute(conn, """
        UPDATE ntk.retrieval_chunks SET embedding = :v, embedding_model = :m, embedded_at = now()
        WHERE id = :id
    """, [{"id": cid, "v": vector_literal(vec), "m": model} for cid, vec in items])


def refresh_normalization(conn: Connection, source_version_id: str) -> int:
    """Recompute normalised text and search forms (citations are untouched)."""
    units = rows(conn, "SELECT id, raw_text FROM ntk.source_units WHERE source_version_id = :sv", {"sv": source_version_id})
    payload = []
    for u in units:
        norm = hebrew.normalize(u["raw_text"])
        payload.append({"id": u["id"], "norm": norm, "terms": hebrew.search_terms(norm),
                        "ngr": hebrew.char_ngrams(norm)[:2000], "nv": hebrew.NORMALIZER_VERSION})
    return execute(conn, """
        UPDATE ntk.source_units SET normalized_text = :norm, search_terms = :terms, char_ngrams = :ngr,
            normalizer_version = :nv WHERE id = :id
    """, payload)


def units_for_version(conn: Connection, source_version_id: str) -> list[dict]:
    return rows(conn, """SELECT * FROM ntk.source_units WHERE source_version_id = :sv ORDER BY unit_ordinal""",
                {"sv": source_version_id})


def counts_for_version(conn: Connection, source_version_id: str) -> dict:
    return row(conn, """
        SELECT (SELECT count(*) FROM ntk.source_units WHERE source_version_id = :sv) AS units,
               (SELECT count(*) FROM ntk.qa_exchanges x JOIN ntk.source_units q ON q.id = x.question_unit_id
                 WHERE q.source_version_id = :sv) AS exchanges,
               (SELECT count(*) FROM ntk.retrieval_chunks WHERE source_version_id = :sv) AS chunks,
               (SELECT count(*) FROM ntk.retrieval_chunks WHERE source_version_id = :sv AND embedding IS NOT NULL) AS embedded
    """, {"sv": source_version_id}) or {}
