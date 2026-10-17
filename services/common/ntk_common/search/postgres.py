"""PostgreSQL search backend (V1 baseline, no OpenSearch).

Signals, each a ranked list of SourceUnit ids, fused with RRF:
  exact   literal identifiers / quoted phrases (ILIKE on normalised text)
  terms   overlap of folded + prefix-stripped + alias terms (GIN on text[])
  trgm    pg_trgm word similarity for OCR noise and spelling variants
  ngram   character 3-gram overlap on retrieval chunks
  vector  pgvector cosine distance on retrieval chunks
  graph   units linked to entities / claims / Project 315 events whose
          names or questions match the query
Filters (case, dates, witness, phase, court_record_status, publication) are
applied inside every signal query, before ranking and generation.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy import Engine, text

from .. import hebrew
from ..db.core import vector_literal
from .base import SIGNALS, SearchHit, SearchRequest, SearchResponse, exact_terms, query_terms, rrf

Embedder = Callable[[str], list[float]]


def _filter_sql(req: SearchRequest, alias: str = "su") -> tuple[str, dict]:
    f = req.filters
    clauses = [f"{alias}.superseded_at IS NULL"]  # units replaced by a re-parse are never search results
    params: dict = {}
    if f.published_only:
        clauses.append("sv.publication_state = 'published'")
    if f.case_id:
        clauses.append("h.case_id = :f_case")
        params["f_case"] = f.case_id
    if f.date_from:
        clauses.append("h.hearing_date >= CAST(:f_from AS date)")
        params["f_from"] = f.date_from
    if f.date_to:
        clauses.append("h.hearing_date <= CAST(:f_to AS date)")
        params["f_to"] = f.date_to
    if f.hearing_id:
        clauses.append(f"{alias}.hearing_id = :f_hid")
        params["f_hid"] = f.hearing_id
    if f.witness:
        clauses.append(f"{alias}.witness_label ILIKE :f_wit")
        params["f_wit"] = f"%{f.witness}%"
    if f.phase:
        clauses.append(f"{alias}.examination_phase = CAST(:f_phase AS ntk.examination_phase)")
        params["f_phase"] = f.phase
    if f.court_record_status:
        clauses.append(f"{alias}.court_record_status = ANY(CAST(:f_crs AS ntk.court_record_status[]))")
        params["f_crs"] = f.court_record_status
    if f.source_types:
        clauses.append(f"""{alias}.source_version_id IN (SELECT fsv.id FROM ntk.source_versions fsv
                         JOIN ntk.source_documents fsd ON fsd.id = fsv.document_id
                         WHERE fsd.source_type::text = ANY(CAST(:f_st AS text[])))""")
        params["f_st"] = list(f.source_types)
    if f.source_version_ids:
        clauses.append(f"{alias}.source_version_id = ANY(CAST(:f_svs AS text[]))")
        params["f_svs"] = list(f.source_version_ids)
    return (" AND ".join(clauses) or "true"), params


UNIT_FROM = """
    FROM ntk.source_units su
    JOIN ntk.source_versions sv ON sv.id = su.source_version_id
    LEFT JOIN ntk.hearings h ON h.id = su.hearing_id
"""


class PostgresSearchBackend:
    name = "postgres-baseline-v1"

    def __init__(self, engine: Engine, embedder: Embedder | None = None, *, aliases: dict[str, list[str]] | None = None,
                 trgm_threshold: float = 0.45, weights: dict[str, float] | None = None,
                 max_vector_distance: float = 0.55):
        self.engine = engine
        self.embedder = embedder
        self.aliases = aliases or {}
        self.trgm_threshold = trgm_threshold
        self.max_vector_distance = max_vector_distance  # cosine distance; tune per embedding model (benchmark)
        self.weights = weights or {"exact": 1.5, "terms": 1.0, "trgm": 0.8, "ngram": 0.6, "vector": 1.0, "graph": 0.7}

    # -- signals -------------------------------------------------------------
    def _exact(self, conn, req, where, params) -> list[str]:
        terms = exact_terms(req.query)
        if not terms:
            return []
        conds = " OR ".join(f"su.normalized_text ILIKE :ex{i}" for i in range(len(terms)))
        p = {**params, **{f"ex{i}": f"%{hebrew.normalize(t)}%" for i, t in enumerate(terms)}, "lim": req.per_signal_limit}
        sql = f"SELECT su.id {UNIT_FROM} WHERE {where} AND ({conds}) ORDER BY su.source_version_id, su.unit_ordinal LIMIT :lim"
        return [r[0] for r in conn.execute(text(sql), p)]

    def _terms(self, conn, req, where, params) -> list[str]:
        qt = query_terms(req.query, self.aliases)
        if not qt:
            return []
        sql = f"""
            SELECT su.id, cardinality(ARRAY(SELECT unnest(su.search_terms) INTERSECT SELECT unnest(CAST(:qt AS text[])))) AS hits
            {UNIT_FROM} WHERE {where} AND su.search_terms && CAST(:qt AS text[])
            ORDER BY hits DESC, length(su.normalized_text) ASC, su.id LIMIT :lim
        """
        return [r[0] for r in conn.execute(text(sql), {**params, "qt": qt, "lim": req.per_signal_limit})]

    def _trgm(self, conn, req, where, params) -> list[str]:
        q = hebrew.normalize(req.query)
        if len(q) < 3:
            return []
        conn.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"), {"t": str(self.trgm_threshold)})
        sql = f"""
            SELECT su.id {UNIT_FROM} WHERE {where} AND :q <% su.normalized_text
            ORDER BY word_similarity(:q, su.normalized_text) DESC, su.id LIMIT :lim
        """
        return [r[0] for r in conn.execute(text(sql), {**params, "q": q, "lim": req.per_signal_limit})]

    def _chunk_to_units(self, conn, chunk_ids: list[str], req, where, params) -> list[str]:
        if not chunk_ids:
            return []
        qt = query_terms(req.query, self.aliases)
        sql = f"""
            SELECT m.chunk_id, su.id,
                   cardinality(ARRAY(SELECT unnest(su.search_terms) INTERSECT SELECT unnest(CAST(:qt AS text[])))) AS hits
            FROM ntk.retrieval_chunk_members m JOIN ntk.source_units su ON su.id = m.source_unit_id
            JOIN ntk.source_versions sv ON sv.id = su.source_version_id
            LEFT JOIN ntk.hearings h ON h.id = su.hearing_id
            WHERE m.chunk_id = ANY(:cids) AND {where}
        """
        by_chunk: dict[str, list[tuple[int, str]]] = {}
        for cid, uid, hits in conn.execute(text(sql), {**params, "cids": chunk_ids, "qt": qt or [""]}):
            by_chunk.setdefault(cid, []).append((hits, uid))
        out: list[str] = []
        for cid in chunk_ids:  # chunk rank order, then best units inside each chunk
            for _, uid in sorted(by_chunk.get(cid, []), key=lambda t: (-t[0], t[1]))[:3]:
                if uid not in out:
                    out.append(uid)
        return out

    def _ngram(self, conn, req, where, params) -> list[str]:
        grams = hebrew.char_ngrams(req.query)
        if len(grams) < 3:
            return []
        cwhere = where.replace("su.", "rc.")
        sql = f"""
            SELECT rc.id, cardinality(ARRAY(SELECT unnest(rc.char_ngrams) INTERSECT SELECT unnest(CAST(:g AS text[])))) AS hits
            FROM ntk.retrieval_chunks rc JOIN ntk.source_versions sv ON sv.id = rc.source_version_id
            LEFT JOIN ntk.hearings h ON h.id = rc.hearing_id
            WHERE rc.char_ngrams && CAST(:g AS text[]) AND {self._chunk_where(req)}
            ORDER BY hits DESC, rc.id LIMIT :lim
        """
        _ = cwhere
        chunk_ids = [r[0] for r in conn.execute(text(sql), {**params, "g": grams, "lim": max(10, req.per_signal_limit // 3)})]
        return self._chunk_to_units(conn, chunk_ids, req, where, params)

    def _chunk_where(self, req: SearchRequest) -> str:
        f = req.filters
        clauses = []
        if f.published_only:
            clauses.append("sv.publication_state = 'published'")
        if f.case_id:
            clauses.append("h.case_id = :f_case")
        if f.date_from:
            clauses.append("h.hearing_date >= CAST(:f_from AS date)")
        if f.date_to:
            clauses.append("h.hearing_date <= CAST(:f_to AS date)")
        if f.hearing_id:
            clauses.append("rc.hearing_id = :f_hid")
        if f.source_version_ids:
            clauses.append("rc.source_version_id = ANY(CAST(:f_svs AS text[]))")
        return " AND ".join(clauses) or "true"

    def _vector(self, conn, req, where, params) -> list[str]:
        if self.embedder is None:
            return []
        vec = self.embedder(req.query)
        sql = f"""
            SELECT rc.id FROM ntk.retrieval_chunks rc JOIN ntk.source_versions sv ON sv.id = rc.source_version_id
            LEFT JOIN ntk.hearings h ON h.id = rc.hearing_id
            WHERE rc.embedding IS NOT NULL AND {self._chunk_where(req)} AND (rc.embedding <=> :v) < :maxd
            ORDER BY rc.embedding <=> :v LIMIT :lim
        """
        chunk_ids = [r[0] for r in conn.execute(text(sql), {**params, "v": vector_literal(vec), "maxd": self.max_vector_distance,
                                                              "lim": max(10, req.per_signal_limit // 3)})]
        return self._chunk_to_units(conn, chunk_ids, req, where, params)

    def _graph(self, conn, req, where, params) -> list[str]:
        qt = query_terms(req.query, self.aliases)
        if not qt:
            return []
        folded = [hebrew.fold(t) for t in qt]
        # entities whose names/aliases match → their spoken units; published claims whose question matches → cited units
        sql = f"""
            WITH ents AS (
              SELECT e.id, e.canonical_name FROM ntk.entities e
              WHERE EXISTS (SELECT 1 FROM unnest(e.aliases || e.canonical_name) n
                            WHERE EXISTS (SELECT 1 FROM unnest(CAST(:ft AS text[])) t WHERE length(t) > 2 AND n ILIKE '%' || t || '%'))
            ),
            ent_units AS (
              SELECT su.id, 1 AS w {UNIT_FROM}
              WHERE {where} AND (su.speaker_entity_id IN (SELECT id FROM ents)
                    OR su.witness_label ILIKE ANY (SELECT '%' || canonical_name || '%' FROM ents))
              LIMIT :lim
            ),
            claim_units AS (
              SELECT ac.source_unit_id AS id, 2 AS w
              FROM ntk.claims c JOIN ntk.generated_artifacts ga ON ga.object_id = c.id::text AND ga.review_state = 'published'
              JOIN ntk.artifact_citations ac ON ac.artifact_id = ga.id
              WHERE EXISTS (SELECT 1 FROM unnest(CAST(:ft AS text[])) t WHERE length(t) > 2 AND c.canonical_question ILIKE '%' || t || '%')
              LIMIT :lim
            ),
            p315_units AS (
              SELECT ps.source_unit_id AS id, 1 AS w FROM ntk.project315_events pe
              JOIN ntk.project315_event_sources ps ON ps.event_id = pe.id
              WHERE ps.source_unit_id IS NOT NULL AND EXISTS (SELECT 1 FROM unnest(CAST(:ft AS text[])) t
                    WHERE length(t) > 2 AND (coalesce(pe.subject,'') || ' ' || coalesce(pe.description,'')) ILIKE '%' || t || '%')
              LIMIT :lim
            )
            SELECT x.id FROM (SELECT * FROM claim_units UNION ALL SELECT * FROM ent_units UNION ALL SELECT * FROM p315_units) x
            JOIN ntk.source_units su ON su.id = x.id JOIN ntk.source_versions sv ON sv.id = su.source_version_id
            LEFT JOIN ntk.hearings h ON h.id = su.hearing_id
            WHERE {where}
            GROUP BY x.id ORDER BY max(x.w) DESC, x.id LIMIT :lim
        """
        return [r[0] for r in conn.execute(text(sql), {**params, "ft": folded, "lim": req.per_signal_limit})]

    # -- main ------------------------------------------------------------------
    def search(self, req: SearchRequest) -> SearchResponse:
        where, params = _filter_sql(req)
        rankings: dict[str, list[str]] = {}
        timings: dict[str, float] = {}
        with self.engine.connect() as conn:
            for sig in SIGNALS:
                if sig not in req.signals:
                    continue
                t0 = time.perf_counter()
                try:
                    with conn.begin_nested() if conn.in_transaction() else conn.begin():
                        rankings[sig] = getattr(self, f"_{sig}")(conn, req, where, params)
                except Exception:  # noqa: BLE001 - one failing signal must not break search
                    rankings[sig] = []
                timings[sig] = round((time.perf_counter() - t0) * 1000, 2)
            fused = rrf(rankings, weights=self.weights)[: req.limit]
            hits = self._hydrate(conn, fused)
        timings["total"] = round(sum(timings.values()), 2)
        return SearchResponse(req.query, hits, {k: len(v) for k, v in rankings.items()}, timings, self.name)

    def _hydrate(self, conn, fused) -> list[SearchHit]:
        if not fused:
            return []
        ids_ = [u for u, _, _ in fused]
        data = {r["id"]: r for r in (dict(x._mapping) for x in conn.execute(text("""
            SELECT su.id, su.page_no, su.line_start, su.line_end, su.speaker_label, su.speaker_role, su.unit_type,
                   su.examination_phase::text AS phase, su.raw_text, su.source_version_id, su.hearing_id,
                   h.hearing_date::text AS hearing_date, su.court_record_status::text AS crs,
                   ARRAY(SELECT chunk_id FROM ntk.retrieval_chunk_members m WHERE m.source_unit_id = su.id) AS chunk_ids
            FROM ntk.source_units su LEFT JOIN ntk.hearings h ON h.id = su.hearing_id WHERE su.id = ANY(:ids)
        """), {"ids": ids_}))}
        out = []
        for uid, score, ranks in fused:
            r = data.get(uid)
            if r is None:
                continue
            out.append(SearchHit(uid, round(score, 6), ranks, r["page_no"], r["line_start"], r["line_end"], r["speaker_label"],
                                 r["speaker_role"], r["unit_type"], r["phase"], r["raw_text"], r["source_version_id"],
                                 r["hearing_id"], r["hearing_date"], r["crs"], list(r["chunk_ids"] or [])))
        return out
