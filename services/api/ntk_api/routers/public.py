"""Public endpoints: published objects only (spec §32, §33.1)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from ntk_common import contracts
from ntk_common.db import public as pub
from ntk_common.db.core import row
from ntk_common.search.base import SearchFilters, SearchRequest

from ..app import ApiError, AppState
from ..deps import get_state, rate_limit
from ..schemas import AskRequest, SearchRequestIn

router = APIRouter(prefix="/v2", tags=["public"])

CACHE_PUBLIC = "public, max-age=60, stale-while-revalidate=300"


def _json(content: Any, *, cache: str | None = CACHE_PUBLIC, status: int = 200) -> JSONResponse:
    resp = JSONResponse(content=_jsonable(content), status_code=status)
    if cache:
        resp.headers["Cache-Control"] = cache
    return resp


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if hasattr(o, "hex") and o.__class__.__name__ == "UUID":
        return str(o)
    if o.__class__.__name__ == "Decimal":
        return float(o)
    if o.__class__.__name__ == "Range":
        return {"lower": _jsonable(o.lower), "upper": _jsonable(o.upper)}
    return o


@router.get("/health", tags=["ops"], include_in_schema=True)
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready", tags=["ops"])
def ready(st: AppState = Depends(get_state)) -> JSONResponse:
    checks = {}
    try:
        with st.services.engine.connect() as conn:
            checks["database"] = row(conn, "SELECT 1 AS ok")["ok"] == 1  # type: ignore[index]
            checks["schema"] = bool(row(conn, "SELECT to_regclass('ntk.source_units') IS NOT NULL AS ok")["ok"])  # type: ignore[index]
    except Exception:  # noqa: BLE001
        checks["database"] = False
    checks["redis"] = st.redis is not None
    ok = checks.get("database") and checks.get("schema")
    return _json({"status": "ok" if ok else "degraded", "checks": checks}, cache="no-store", status=200 if ok else 503)


@router.get("/status", dependencies=[Depends(rate_limit("public"))])
def status(st: AppState = Depends(get_state)) -> JSONResponse:
    with st.services.engine.connect() as conn:
        stats = pub.corpus_stats(conn)
        timeline = pub.public_timeline(conn, case_id=st.settings.case_id)
    return _json({"case_id": st.settings.case_id, "corpus": stats,
                  "outcome_events": [e for e in timeline if e["outcome"]],
                  "recent_events": timeline[-10:]})


@router.get("/claims", dependencies=[Depends(rate_limit("public"))])
def list_claims(st: AppState = Depends(get_state)) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": pub.public_claims(conn)})


@router.get("/claims/{claim_id}", dependencies=[Depends(rate_limit("public"))],
            responses={404: {"description": "not found or not published"}})
def get_claim(claim_id: str, st: AppState = Depends(get_state),
              as_of: dt.datetime | None = Query(default=None, description="valid time in the proceeding"),
              known_at: dt.datetime | None = Query(default=None, description="system time: what the site knew then")) -> JSONResponse:
    _uuid(claim_id)
    with st.services.engine.connect() as conn:
        card = pub.public_claim_card(conn, claim_id, as_of=as_of, known_at=known_at)
    if card is None:
        raise ApiError(404, "unpublished_object", "claim card not found or not published")
    contracts.validate("ClaimBundle", card["bundle"])
    return _json(card)


@router.get("/claims/{claim_id}/evidence", dependencies=[Depends(rate_limit("public"))])
def get_claim_evidence(claim_id: str, st: AppState = Depends(get_state)) -> JSONResponse:
    _uuid(claim_id)
    with st.services.engine.connect() as conn:
        card = pub.public_claim_card(conn, claim_id)
    if card is None:
        raise ApiError(404, "unpublished_object", "claim card not found or not published")
    b = card["bundle"]
    cits = {c["source_unit_id"]: c for c in b["citations"]}
    def expand(points):
        return [{**p, "citations": [cits[c] for c in p["citation_ids"] if c in cits]} for p in points]
    return _json({"claim_id": claim_id, "support": expand(b["support"]), "weakness": expand(b["weakness"]),
                  "court_position": b["court_position"], "as_of": b["as_of"]})


@router.get("/hearings", dependencies=[Depends(rate_limit("public"))])
def list_hearings(st: AppState = Depends(get_state)) -> JSONResponse:
    with st.services.engine.connect() as conn:
        return _json({"items": pub.public_hearings(conn)})


@router.get("/hearings/{hearing_id}", dependencies=[Depends(rate_limit("public"))])
def get_hearing(hearing_id: str, st: AppState = Depends(get_state)) -> JSONResponse:
    with st.services.engine.connect() as conn:
        h = pub.public_hearing(conn, hearing_id)
    if h is None:
        raise ApiError(404, "unpublished_object", "hearing not found or not published")
    return _json(h)


@router.get("/timeline", dependencies=[Depends(rate_limit("public"))])
def timeline(st: AppState = Depends(get_state), as_of: dt.datetime | None = None, known_at: dt.datetime | None = None) -> JSONResponse:
    with st.services.engine.connect() as conn:
        events = pub.public_timeline(conn, case_id=st.settings.case_id, as_of=as_of, known_at=known_at)
        hearings = pub.public_hearings(conn)
    return _json({"as_of": as_of, "events": events, "hearings": hearings})


@router.get("/sources/{document_id}/versions/{version_id}", dependencies=[Depends(rate_limit("public"))])
def get_source_version(document_id: str, version_id: str, st: AppState = Depends(get_state)) -> JSONResponse:
    with st.services.engine.connect() as conn:
        sv = pub.public_source_version(conn, document_id, version_id)
    if sv is None:
        raise ApiError(404, "unpublished_object", "source version not found or not published")
    return _json(sv)


@router.get("/citations/{source_unit_id}", dependencies=[Depends(rate_limit("public"))])
def get_citation(source_unit_id: str, st: AppState = Depends(get_state)) -> JSONResponse:
    if not (source_unit_id.startswith("su_") and len(source_unit_id) == 29):
        raise ApiError(400, "invalid_request", "invalid source unit id")
    with st.services.engine.connect() as conn:
        c = pub.public_citation(conn, source_unit_id)
    if c is None:
        raise ApiError(404, "unpublished_object", "citation not found or source not published")
    u = c["unit"]
    citation = {"source_unit_id": u["id"], "source_version_id": u["source_version_id"], "page": u["page_no"],
                "line_start": u["line_start"], "line_end": u["line_end"], "speaker": u["speaker_label"],
                "quote": None, "court_record_status": u["crs"], "permalink": f"{st.settings.citation_base}{u['id']}"}
    contracts.validate("Citation", citation)
    return _json({"citation": citation, "text": u["raw_text"], "unit_type": u["unit_type"],
                  "examination_phase": u["phase"], "synthetic_lines": u["synthetic_lines"],
                  "witness": u["witness_label"], "hearing_id": u["hearing_id"], "hearing_date": u["hearing_date"],
                  "document": {"id": u["document_id"], "title": u["canonical_title"], "source_type": u["source_type"],
                               "authority_tier": u["authority_tier"], "source_owner": u["source_owner"],
                               "canonical_url": u["canonical_url"], "content_sha256": u["content_sha256"]},
                  "superseded_by_version": u["superseded_by"], "turn_continuations": c["turn_continuations"],
                  "context": c["context"], "exchange": c["exchange"]}, cache="public, max-age=3600")


@router.post("/search", dependencies=[Depends(rate_limit("search"))])
def search(body: SearchRequestIn, st: AppState = Depends(get_state)) -> JSONResponse:
    f = body.filters
    req = SearchRequest(body.query, SearchFilters(
        case_id=None, date_from=f.date_from.isoformat() if f.date_from else None,
        date_to=f.date_to.isoformat() if f.date_to else None, witness=f.witness, phase=f.phase,
        court_record_status=list(f.court_record_status) if f.court_record_status else None, hearing_id=f.hearing_id,
        published_only=True), limit=body.limit)
    resp = st.services.search_backend().search(req)
    return _json({
        "query": resp.query, "backend": resp.backend, "signal_counts": resp.signal_counts, "timings_ms": resp.timings_ms,
        "hits": [{"source_unit_id": h.source_unit_id, "score": h.score, "signals": h.signals, "page": h.page,
                  "line_start": h.line_start, "line_end": h.line_end, "speaker": h.speaker_label, "unit_type": h.unit_type,
                  "examination_phase": h.examination_phase, "text": h.text, "hearing_id": h.hearing_id,
                  "hearing_date": h.hearing_date, "court_record_status": h.court_record_status,
                  "permalink": f"{st.settings.citation_base}{h.source_unit_id}"} for h in resp.hits],
    }, cache="public, max-age=60")


@router.post("/ask", dependencies=[Depends(rate_limit("ask"))],
             responses={200: {"description": "AnswerEnvelope (contracts/ntk-contracts-2.0.json#/$defs/AnswerEnvelope)"}})
def ask(body: AskRequest, request: Request, st: AppState = Depends(get_state)) -> JSONResponse:
    if len(body.question) > st.settings.max_question_chars:
        raise ApiError(400, "invalid_request", f"question longer than {st.settings.max_question_chars} characters")
    try:
        res = st.ask.answer(body.question, as_of=body.as_of, locale=body.locale, client_request_id=body.client_request_id)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", str(exc)) from exc
    return _json(res.envelope, cache="no-store")


@router.get("/answers/{answer_id}", dependencies=[Depends(rate_limit("public"))])
def get_answer(answer_id: str, st: AppState = Depends(get_state)) -> JSONResponse:
    _uuid(answer_id)
    with st.services.engine.connect() as conn:
        env = pub.answer_by_id(conn, answer_id)
    if env is None:
        raise ApiError(404, "not_found", "answer not found")
    historical = env.pop("_historical", False)
    resp = _json(env, cache="public, max-age=600")
    resp.headers["X-NTK-Historical"] = "1" if historical else "0"
    return resp


def _uuid(v: str) -> None:
    import uuid as _u

    try:
        _u.UUID(v)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "invalid id") from exc
