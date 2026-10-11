"""Public read models and the PostgreSQL AskStore.

Every query here enforces the publication boundary: units only from
published SourceVersions, artifacts only with a live publication.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from .. import hebrew
from ..layers import UnitView
from .core import execute, j, row, rows, scalar
from .ops import audit, current_corpus_version

UNIT_COLS = """su.id, su.source_version_id, su.page_no, su.line_start, su.line_end, su.speaker_label, su.speaker_role,
    su.unit_type, su.raw_text, su.court_record_status::text AS crs, su.hearing_id, su.examination_phase::text AS phase,
    su.turn_key, su.turn_part, su.synthetic_lines, su.witness_label, su.unit_ordinal"""


def unit_view(r: dict, *, published: bool, jl: tuple[str, bool] | None = None) -> UnitView:
    return UnitView(id=r["id"], source_version_id=r["source_version_id"], page=r["page_no"], line_start=r["line_start"],
                    line_end=r["line_end"], speaker_label=r["speaker_label"], speaker_role=r["speaker_role"],
                    unit_type=r["unit_type"], text=r["raw_text"], court_record_status=r["crs"], published=published,
                    hearing_id=r["hearing_id"], examination_phase=r["phase"],
                    judicial_level=jl[0] if jl else None, judicial_human_approved=bool(jl and jl[1]))


def judicial_map(conn: Connection, unit_ids: list[str]) -> dict[str, tuple[str, bool]]:
    from .knowledge import judicial_levels_for

    return judicial_levels_for(conn, unit_ids) if unit_ids else {}


def units_by_ids(conn: Connection, unit_ids: list[str], *, published_only: bool) -> dict[str, UnitView]:
    if not unit_ids:
        return {}
    pub = "AND sv.publication_state = 'published'" if published_only else ""
    data = rows(conn, f"""
        SELECT {UNIT_COLS}, (sv.publication_state = 'published') AS published
        FROM ntk.source_units su JOIN ntk.source_versions sv ON sv.id = su.source_version_id
        WHERE su.id = ANY(:ids) {pub}
    """, {"ids": list(unit_ids)})
    jm = judicial_map(conn, [r["id"] for r in data])
    return {r["id"]: unit_view(r, published=r["published"], jl=jm.get(r["id"])) for r in data}


# ------------------------------------------------------------------ public endpoints
def public_citation(conn: Connection, unit_id: str) -> dict | None:
    r = row(conn, f"""
        SELECT {UNIT_COLS}, sv.document_id, sv.content_sha256, sv.page_count, sv.retrieved_at, sv.supersedes_id,
               d.canonical_title, d.source_type::text AS source_type, d.authority_tier, d.source_owner, d.canonical_url,
               h.hearing_date::text AS hearing_date,
               (SELECT n.id FROM ntk.source_versions n WHERE n.supersedes_id = sv.id AND n.publication_state = 'published'
                ORDER BY n.retrieved_at DESC LIMIT 1) AS superseded_by
        FROM ntk.source_units su JOIN ntk.source_versions sv ON sv.id = su.source_version_id
        JOIN ntk.source_documents d ON d.id = sv.document_id
        LEFT JOIN ntk.hearings h ON h.id = su.hearing_id
        WHERE su.id = :id AND sv.publication_state = 'published'
    """, {"id": unit_id})
    if r is None:
        return None
    siblings = rows(conn, """SELECT id, page_no, line_start, line_end, turn_part, raw_text FROM ntk.source_units
                             WHERE turn_key = :tk AND id <> :id ORDER BY turn_part""",
                    {"tk": r["turn_key"], "id": unit_id}) if r["turn_key"] else []
    neighbours = rows(conn, """SELECT id, page_no, line_start, line_end, speaker_label, unit_type, raw_text
                               FROM ntk.source_units WHERE source_version_id = :sv AND superseded_at IS NULL
                               AND unit_ordinal BETWEEN :o - 2 AND :o + 2 AND id <> :id ORDER BY unit_ordinal""",
                      {"sv": r["source_version_id"], "o": r["unit_ordinal"], "id": unit_id})
    exchange = row(conn, """SELECT id, question_unit_id, answer_unit_id, answer_relation::text AS answer_relation,
                                   public_wording, review_state::text AS review_state
                            FROM ntk.qa_exchanges WHERE (question_unit_id = :id OR answer_unit_id = :id)
                            AND superseded_at IS NULL LIMIT 1""",
                   {"id": unit_id})
    xv = scalar(conn, "SELECT extractor_version FROM ntk.source_versions WHERE id = :sv", {"sv": r["source_version_id"]})
    for x in [r, *siblings, *neighbours]:
        x["raw_text"] = hebrew.display_text(x["raw_text"], xv)
    return {"unit": r, "turn_continuations": siblings, "context": neighbours, "exchange": exchange}


def public_source_version(conn: Connection, document_id: str, version_id: str) -> dict | None:
    return row(conn, """
        SELECT sv.id, sv.document_id, sv.content_sha256, sv.retrieved_at, sv.published_at, sv.mime_type, sv.page_count,
               sv.parser_version, sv.extractor_version, sv.supersedes_id, sv.synthetic_lines, sv.court_record_status::text AS crs,
               sv.size_bytes, sv.source_url, d.canonical_title, d.source_type::text AS source_type, d.authority_tier,
               d.source_owner, d.source_stance, d.canonical_url, d.legal_access_notes,
               (SELECT count(*) FROM ntk.source_units su WHERE su.source_version_id = sv.id
                  AND su.superseded_at IS NULL) AS unit_count
        FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
        WHERE sv.id = :v AND sv.document_id = :d AND sv.publication_state = 'published'
    """, {"v": version_id, "d": document_id})


def public_claim_card(conn: Connection, claim_id: str, *, as_of: Any = None, known_at: Any = None) -> dict | None:
    """Published claim card as known at ``known_at`` (system time); status as
    valid at ``as_of`` (valid time)."""
    card = row(conn, """
        SELECT ga.id, ga.payload, ga.created_at, p.published_at, p.canonical_url, p.knowledge_version, p.unpublished_at
        FROM ntk.generated_artifacts ga JOIN ntk.publications p ON p.artifact_id = ga.id
        WHERE ga.artifact_type = 'claim_card' AND ga.object_type = 'claim' AND ga.object_id = :c
          AND p.published_at <= coalesce(CAST(:known AS timestamptz), now())
          AND (p.unpublished_at IS NULL OR p.unpublished_at > coalesce(CAST(:known AS timestamptz), now()))
        ORDER BY p.published_at DESC LIMIT 1
    """, {"c": claim_id, "known": known_at})
    if card is None:
        return None
    from .knowledge import current_claim_status

    status = current_claim_status(conn, claim_id, as_of=as_of, known_at=known_at)
    return {"artifact_id": str(card["id"]), "bundle": card["payload"], "published_at": card["published_at"],
            "canonical_url": card["canonical_url"], "knowledge_version": card["knowledge_version"], "status_as_of": status}


def public_claims(conn: Connection) -> list[dict]:
    return rows(conn, """
        SELECT ga.object_id AS claim_id, ga.payload->>'question' AS question, ga.payload->>'status' AS status,
               ga.payload->>'answer_short' AS answer_short, p.published_at, c.slug, c.thesis_code,
               v.editorial_priority
        FROM ntk.generated_artifacts ga JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
        JOIN ntk.claims c ON c.id::text = ga.object_id
        JOIN LATERAL (SELECT editorial_priority FROM ntk.claim_versions v WHERE v.claim_id = c.id
                      AND upper(v.recorded_during) IS NULL ORDER BY created_at DESC LIMIT 1) v ON true
        WHERE ga.artifact_type = 'claim_card' AND ga.review_state = 'published'
        ORDER BY v.editorial_priority DESC, p.published_at DESC
    """)


def public_hearing(conn: Connection, hearing_id: str) -> dict | None:
    h = row(conn, """
        SELECT h.id, h.case_id, h.hearing_date::text AS hearing_date, h.location, h.phase, h.judges, h.witnesses,
               h.source_version_id, sv.document_id
        FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE h.id = :id AND sv.publication_state = 'published'
    """, {"id": hearing_id})
    if h is None:
        return None
    digest = row(conn, """
        SELECT ga.id, ga.payload FROM ntk.generated_artifacts ga JOIN ntk.publications p ON p.artifact_id = ga.id
        AND p.unpublished_at IS NULL WHERE ga.artifact_type = 'summary' AND ga.object_type = 'hearing' AND ga.object_id = :id
        ORDER BY p.published_at DESC LIMIT 1
    """, {"id": hearing_id})
    stats = row(conn, """SELECT count(*) AS units, count(*) FILTER (WHERE unit_type='question') AS questions,
                                count(*) FILTER (WHERE unit_type='answer') AS answers
                         FROM ntk.source_units WHERE hearing_id = :id AND superseded_at IS NULL""", {"id": hearing_id})
    return {"hearing": h, "digest": digest["payload"] if digest else None,
            "digest_artifact_id": str(digest["id"]) if digest else None, "stats": stats}


def public_hearings(conn: Connection) -> list[dict]:
    return rows(conn, """
        SELECT h.id, h.hearing_date::text AS hearing_date, h.witnesses, h.judges, sv.document_id, h.source_version_id,
               EXISTS (SELECT 1 FROM ntk.generated_artifacts ga JOIN ntk.publications p ON p.artifact_id = ga.id
                       AND p.unpublished_at IS NULL WHERE ga.object_type='hearing' AND ga.object_id = h.id) AS has_digest
        FROM ntk.hearings h JOIN ntk.source_versions sv ON sv.id = h.source_version_id
        WHERE sv.publication_state = 'published' ORDER BY h.hearing_date
    """)


def public_timeline(conn: Connection, *, case_id: str, as_of: Any = None, known_at: Any = None) -> list[dict]:
    return rows(conn, """
        SELECT id, event_type, occurred_at, outcome::text AS outcome, title, description, source_unit_ids,
               external_sources, lower(valid_during) AS valid_from, upper(valid_during) AS valid_to
        FROM ntk.case_events
        WHERE case_id = :c AND review_state = 'published'
          AND lower(valid_during) <= coalesce(CAST(:as_of AS timestamptz), now())
          AND recorded_during @> coalesce(CAST(:known AS timestamptz), now())
        ORDER BY occurred_at
    """, {"c": case_id, "as_of": as_of, "known": known_at})


def answer_by_id(conn: Connection, answer_id: str) -> dict | None:
    a = row(conn, "SELECT * FROM ntk.answers WHERE id = CAST(:id AS uuid)", {"id": answer_id})
    if a is None:
        return None
    env = dict(a["envelope"])
    latest = row(conn, """SELECT id, envelope->>'permalink' AS permalink FROM ntk.answers
                          WHERE normalized_question = :q AND locale = :l AND id <> :id
                          ORDER BY created_at DESC LIMIT 1""",
                 {"q": a["normalized_question"], "l": a["locale"], "id": a["id"]})
    cv_now = current_corpus_version(conn)
    if latest and str(latest["id"]) != str(a["id"]) and a["corpus_version"] != cv_now:
        env["latest_permalink"] = latest["permalink"]
    env["_historical"] = a["corpus_version"] != cv_now
    return env


# ------------------------------------------------------------------ AskStore
class PgAskStore:
    def __init__(self, engine: Engine, *, case_id: str):
        self.engine = engine
        self.case_id = case_id

    def corpus_version(self) -> str:
        with self.engine.connect() as conn:
            return current_corpus_version(conn)

    def outcome_events(self, as_of: dt.datetime) -> list[dict]:
        with self.engine.connect() as conn:
            return [e for e in public_timeline(conn, case_id=self.case_id, as_of=as_of) if e["outcome"]]

    def process_events(self, as_of: dt.datetime) -> list[dict]:
        with self.engine.connect() as conn:
            evs = public_timeline(conn, case_id=self.case_id, as_of=as_of)
        for e in evs:
            e["occurred_at"] = e["occurred_at"].isoformat()
        return [e for e in evs if e["event_type"] in {"pardon_requested", "status_change", "outcome"}]

    def published_claim_cards(self) -> list[dict]:
        with self.engine.connect() as conn:
            return rows(conn, """SELECT ga.object_id, ga.payload FROM ntk.public_artifacts ga
                                 WHERE ga.artifact_type = 'claim_card'""")

    def published_digests(self) -> list[dict]:
        with self.engine.connect() as conn:
            return rows(conn, """SELECT ga.object_id, ga.payload FROM ntk.public_artifacts ga
                                 WHERE ga.artifact_type = 'summary' AND ga.object_type = 'hearing'""")

    def public_units(self, unit_ids: list[str]) -> dict[str, UnitView]:
        with self.engine.connect() as conn:
            return units_by_ids(conn, unit_ids, published_only=True)

    def exchange_partners(self, unit_ids: list[str]) -> dict[str, str]:
        """For question/answer units, the unit on the other side of their Q/A exchange (question→answer, answer→question)."""
        if not unit_ids:
            return {}
        with self.engine.connect() as conn:
            out: dict[str, str] = {}
            for r in rows(conn, """SELECT question_unit_id AS q, answer_unit_id AS a FROM ntk.qa_exchanges
                                   WHERE (question_unit_id = ANY(:ids) OR answer_unit_id = ANY(:ids))
                                   AND superseded_at IS NULL""", {"ids": unit_ids}):
                out.setdefault(r["q"], r["a"])
                out.setdefault(r["a"], r["q"])
            return out

    def published_hearings(self) -> list[dict]:
        with self.engine.connect() as conn:
            return rows(conn, """SELECT h.hearing_date::text AS hearing_date, h.witnesses FROM ntk.hearings h
                                 JOIN ntk.source_versions sv ON sv.id = h.source_version_id
                                 WHERE sv.publication_state = 'published' AND h.case_id = :c ORDER BY h.hearing_date""",
                        {"c": self.case_id})

    def approved_rulings(self) -> list[dict]:
        with self.engine.connect() as conn:
            return rows(conn, """
                SELECT js.source_unit_id, js.level::text AS level, js.summary, su.raw_text AS text
                FROM ntk.judicial_statements js JOIN ntk.source_units su ON su.id = js.source_unit_id
                JOIN ntk.source_versions sv ON sv.id = su.source_version_id AND sv.publication_state = 'published'
                WHERE js.review_state IN ('approved','published') AND js.level IN ('procedural_decision','substantive_ruling')
            """)

    def judicial_statements_for_terms(self, terms: list[str]) -> list[dict]:
        with self.engine.connect() as conn:
            return rows(conn, """
                SELECT js.source_unit_id, js.level::text AS level, js.summary
                FROM ntk.judicial_statements js JOIN ntk.source_units su ON su.id = js.source_unit_id
                JOIN ntk.source_versions sv ON sv.id = su.source_version_id AND sv.publication_state = 'published'
                WHERE su.search_terms && CAST(:t AS text[])
                ORDER BY cardinality(ARRAY(SELECT unnest(su.search_terms) INTERSECT SELECT unnest(CAST(:t AS text[])))) DESC
                LIMIT 5
            """, {"t": terms})

    def find_answer(self, key: dict) -> dict | None:
        with self.engine.connect() as conn:
            return row(conn, """
                SELECT envelope, gate_report, retrieval_ids FROM ntk.answers
                WHERE normalized_question = :normalized_question AND as_of::date = CAST(:as_of_date AS date)
                  AND corpus_version = :corpus_version AND prompt_version = :prompt_version
                  AND model_version = :model_version AND locale = :locale
                ORDER BY created_at DESC LIMIT 1
            """, key)

    def save_answer(self, record: dict) -> None:
        with self.engine.begin() as conn:
            execute(conn, """
                INSERT INTO ntk.answers (id, slug, question, normalized_question, locale, as_of, corpus_version, prompt_version,
                    model_version, answer_status, envelope, retrieval_ids, gate_report, model_run_id, client_request_id)
                VALUES (CAST(:answer_id AS uuid), :answer_id, :question, :normalized_question, :locale,
                    CAST(:as_of_date AS timestamptz), :corpus_version, :prompt_version, :model_version, :answer_status,
                    CAST(:env AS jsonb), :retrieval_ids, CAST(:gr AS jsonb), CAST(:model_run_id AS uuid), :client_request_id)
                ON CONFLICT DO NOTHING
            """, {**record, "env": j(record["envelope"]), "gr": j(record.get("gate_report", {})),
                  "model_run_id": record.get("model_run_id")})
            audit(conn, actor="public", action="ask.answer", object_type="answer", object_id=record["answer_id"],
                  request_id=record.get("client_request_id"),
                  details={"status": record["answer_status"], "corpus_version": record["corpus_version"],
                           "retrieval_ids": record.get("retrieval_ids", [])[:50], "gates": record.get("gate_report", {})})


def corpus_stats(conn: Connection) -> dict:
    return row(conn, """
        SELECT (SELECT count(*) FROM ntk.source_versions WHERE publication_state='published') AS published_sources,
               (SELECT count(*) FROM ntk.public_source_units) AS published_units,
               (SELECT count(*) FROM ntk.public_artifacts WHERE artifact_type='claim_card') AS claim_cards,
               (SELECT count(*) FROM ntk.public_artifacts WHERE artifact_type='summary') AS digests,
               (SELECT id FROM ntk.corpus_versions ORDER BY seq DESC LIMIT 1) AS corpus_version
    """) or {}


_ = scalar  # re-exported helper kept for callers


# ---------------------------------------------------------------------------
# full text of published sources (transcripts and documents)
# ---------------------------------------------------------------------------
TEXT_PAGES_MAX = 25
LABEL_STATES = ("machine_verified", "approved", "published")


def source_text(conn: Connection, source_version_id: str, *, page_from: int, page_to: int) -> list[dict]:
    """Units of a published source version on pages [page_from, page_to], in reading order, each with its Q/A
    exchange (question→answer link) and, when verified, the affirmed/denied label."""
    out = rows(conn, """
        SELECT su.id, su.page_no AS page, su.line_start, su.line_end, su.speaker_label AS speaker, su.speaker_role,
               su.unit_type, su.examination_phase::text AS phase, su.raw_text AS text, su.witness_label AS witness,
               sv.extractor_version AS _xv,
               x.id AS exchange_id, x.question_unit_id, x.answer_unit_id, x.answer_relation::text AS answer_relation,
               CASE WHEN x.review_state::text = ANY(:ls) THEN x.public_wording END AS exchange_label
        FROM ntk.source_units su
        JOIN ntk.source_versions sv ON sv.id = su.source_version_id AND sv.publication_state = 'published'
        LEFT JOIN ntk.qa_exchanges x ON x.answer_unit_id = su.id AND x.superseded_at IS NULL
        WHERE su.source_version_id = :sv AND su.page_no BETWEEN :a AND :b AND su.superseded_at IS NULL
        ORDER BY su.unit_ordinal
    """, {"sv": source_version_id, "a": page_from, "b": page_to, "ls": list(LABEL_STATES)})
    for r in out:
        r["text"] = hebrew.display_text(r["text"], r.pop("_xv"))
    return out


_BRIEF_JOIN = """
        LEFT JOIN LATERAL (
            SELECT ga.payload AS brief FROM ntk.generated_artifacts ga
            JOIN ntk.publications pb ON pb.artifact_id = ga.id AND pb.unpublished_at IS NULL
            WHERE ga.artifact_type = 'summary' AND ga.object_type = 'document' AND ga.object_id = sv.id
            ORDER BY pb.published_at DESC LIMIT 1) b ON true"""


def _with_brief(r: dict) -> dict:
    b = r.pop("brief", None)
    r["brief"] = None if not b else {
        "title": b["title"]["text"], "summary": " ".join(x["text"] for x in b["summary_sentences"]),
        "significance": b["significance"], "significance_reason": b.get("significance_reason"),
        "hearing_days": b.get("hearing_days") or []}
    r["display_title"] = r["brief"]["title"] if r["brief"] else r["title"]
    r["significance"] = r["brief"]["significance"] if r["brief"] else None
    return r


def public_documents(conn: Connection, *, source_type: str | None, limit: int, offset: int,
                     significance: str | None = None) -> list[dict]:
    """Published sources that are not hearing protocols (decisions, motions, notices, …), newest first. Each carries
    its published brief (title, summary, significance) when there is one. ``significance='substantive'`` keeps the
    documents not judged purely procedural (documents without a brief yet are kept)."""
    return [_with_brief(r) for r in rows(conn, f"""
        SELECT sv.id AS source_version_id, d.id AS document_id, d.canonical_title AS title, d.source_type::text AS source_type,
               d.source_owner, sv.page_count, coalesce(sv.metadata->>'document_date', '') AS document_date,
               sv.publication_changed_at AS published_at, b.brief
        FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id {_BRIEF_JOIN}
        WHERE sv.publication_state = 'published' AND d.source_type <> 'protocol'
          AND (CAST(:t AS text) IS NULL OR d.source_type::text = :t)
          AND (CAST(:sig AS text) IS NULL OR coalesce(b.brief->>'significance', 'substantive') = :sig)
          AND NOT EXISTS (SELECT 1 FROM ntk.source_versions newer WHERE newer.supersedes_id = sv.id
                          AND newer.publication_state = 'published')
        ORDER BY nullif(sv.metadata->>'document_date', '') DESC NULLS LAST, sv.publication_changed_at DESC
        LIMIT :lim OFFSET :off
    """, {"t": source_type, "lim": limit, "off": offset, "sig": significance})]


def public_document(conn: Connection, source_version_id: str) -> dict | None:
    r = row(conn, f"""
        SELECT sv.id AS source_version_id, d.id AS document_id, d.canonical_title AS title, d.source_type::text AS source_type,
               d.source_owner, d.authority_tier, sv.page_count, sv.metadata->>'document_date' AS document_date,
               sv.content_sha256, sv.court_record_status::text AS court_record_status, sv.synthetic_lines,
               (SELECT h.id FROM ntk.hearings h WHERE h.source_version_id = sv.id LIMIT 1) AS hearing_id,
               (SELECT h.hearing_date::text FROM ntk.hearings h WHERE h.source_version_id = sv.id LIMIT 1) AS hearing_date,
               b.brief
        FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id {_BRIEF_JOIN}
        WHERE sv.id = :sv AND sv.publication_state = 'published'
    """, {"sv": source_version_id})
    if r is None:
        return None
    full = r.get("brief")
    out = _with_brief(r)
    if full:
        out["brief"]["summary_sentences"] = full["summary_sentences"]
        out["brief"]["title_citation_ids"] = full["title"]["citation_ids"]
        out["brief"]["citations"] = full["citations"]
    return out


def published_object_key(conn: Connection, source_version_id: str) -> str | None:
    r = row(conn, """SELECT s3_key, object_uri FROM ntk.source_versions
                     WHERE id = :sv AND publication_state = 'published'""", {"sv": source_version_id})
    if r is None:
        return None
    if r.get("s3_key"):
        return r["s3_key"]
    uri = r.get("object_uri") or ""
    return uri.split("/", 3)[3] if uri.startswith("s3://") and uri.count("/") >= 3 else None
