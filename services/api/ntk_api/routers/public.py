"""Public endpoints: published objects only (spec §32, §33.1)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
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


def _page_range(page_from: int, page_to: int | None, page_count: int | None) -> tuple[int, int]:
    last = page_count or page_from
    a = max(1, page_from)
    b = min(last, page_to if page_to is not None else a + pub.TEXT_PAGES_MAX - 1, a + pub.TEXT_PAGES_MAX - 1)
    return a, max(a, b)


def _with_pages(meta: dict, units: list[dict], a: int, b: int) -> dict:
    count = meta.get("page_count") or b
    return {**meta, "page_from": a, "page_to": b, "page_count": count,
            "next_page_from": b + 1 if b < count else None, "prev_page_from": max(1, a - pub.TEXT_PAGES_MAX) if a > 1 else None,
            "units": units}


@router.get("/hearings/{hearing_id}/transcript", dependencies=[Depends(rate_limit("public"))])
def hearing_transcript(hearing_id: str, st: AppState = Depends(get_state), page_from: int = Query(1, ge=1),
                       page_to: int | None = Query(None, ge=1)) -> JSONResponse:
    """The protocol itself, page by page (at most 25 pages per call), with speakers and Q/A links."""
    with st.services.engine.connect() as conn:
        h = pub.public_hearing(conn, hearing_id)
        if h is None:
            raise ApiError(404, "unpublished_object", "hearing not found or not published")
        doc = pub.public_document(conn, h["hearing"]["source_version_id"])
        a, b = _page_range(page_from, page_to, doc["page_count"] if doc else None)
        units = pub.source_text(conn, h["hearing"]["source_version_id"], page_from=a, page_to=b)
    meta = {"hearing": h["hearing"], "document": doc, "page_count": doc["page_count"] if doc else None,
            "pdf_url": f"{st.settings.public_base_url.rstrip('/')}/v2/sources/{h['hearing']['source_version_id']}/pdf"}
    return _json(_with_pages(meta, units, a, b))


@router.get("/documents", dependencies=[Depends(rate_limit("public"))])
def list_documents(st: AppState = Depends(get_state), type: str | None = None,  # noqa: A002 - public query name
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   significance: str | None = Query(None, pattern="^(substantive|procedural)$")) -> JSONResponse:
    with st.services.engine.connect() as conn:
        items = pub.public_documents(conn, source_type=type, limit=limit, offset=offset, significance=significance)
    return _json({"items": items, "limit": limit, "offset": offset, "significance": significance})


@router.get("/documents/{source_version_id}", dependencies=[Depends(rate_limit("public"))])
def get_document(source_version_id: str, st: AppState = Depends(get_state), page_from: int = Query(1, ge=1),
                 page_to: int | None = Query(None, ge=1)) -> JSONResponse:
    if not (source_version_id.startswith("sv_") and len(source_version_id) == 29):
        raise ApiError(400, "invalid_request", "invalid source version id")
    with st.services.engine.connect() as conn:
        doc = pub.public_document(conn, source_version_id)
        if doc is None:
            raise ApiError(404, "unpublished_object", "document not found or not published")
        a, b = _page_range(page_from, page_to, doc["page_count"])
        units = pub.source_text(conn, source_version_id, page_from=a, page_to=b)
    meta = {"document": doc, "page_count": doc["page_count"],
            "pdf_url": f"{st.settings.public_base_url.rstrip('/')}/v2/sources/{source_version_id}/pdf"}
    return _json(_with_pages(meta, units, a, b))


@router.get("/sources/{source_version_id}/pdf", dependencies=[Depends(rate_limit("public"))])
def source_pdf(source_version_id: str, st: AppState = Depends(get_state)):
    """Redirect to a short-lived signed URL of the original PDF (published sources only)."""
    if not (source_version_id.startswith("sv_") and len(source_version_id) == 29):
        raise ApiError(400, "invalid_request", "invalid source version id")
    with st.services.engine.connect() as conn:
        key = pub.published_object_key(conn, source_version_id)
        doc = pub.public_document(conn, source_version_id) if key else None
    if key is None or st.services.storage is None:
        raise ApiError(404, "unpublished_object", "source not found or not published")
    name = f"{(doc or {}).get('title') or source_version_id}"[:120].replace("/", "-") + ".pdf"
    url = st.services.storage.presign_get(key, ttl=300, filename=name)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/timeline", dependencies=[Depends(rate_limit("public"))])
def timeline(st: AppState = Depends(get_state), as_of: dt.datetime | None = None, known_at: dt.datetime | None = None) -> JSONResponse:
    with st.services.engine.connect() as conn:
        events = pub.public_timeline(conn, case_id=st.settings.case_id, as_of=as_of, known_at=known_at)
        hearings = pub.public_hearings(conn)
        documents = pub.public_documents(conn, source_type=None, limit=500, offset=0)
    return _json({"as_of": as_of, "events": events, "hearings": hearings, "documents": documents})


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
    from ntk_common import editorial
    from ntk_common.ask import AskLimited

    from ..ask_budget import MESSAGES, AskBudget

    budget = AskBudget(st.redis, daily_limit=st.settings.ask_daily_limit, visitor_limit=st.settings.ask_visitor_daily_limit)
    visitor = getattr(request.state, "ip_hash", None)
    try:
        res = st.ask.answer(body.question, as_of=body.as_of, locale=body.locale, client_request_id=body.client_request_id,
                            before_model=lambda: budget.reserve(visitor))
    except AskLimited as exc:
        budget.count("limited")
        raise ApiError(429, exc.reason, MESSAGES.get(exc.reason, "")) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_request", str(exc)) from exc
    budget.count("total")
    if res.cached or not res.model_run_id:  # a new answer was counted by reserve()
        budget.count("cached" if res.cached else "free")
    return _json(editorial.polish(res.envelope), cache="no-store")


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


# ------------------------------------------------------------------ reader guides (ADR-0015)
@router.get("/guide", dependencies=[Depends(rate_limit("public"))])
def guide_home(st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import guides_public as gp

    with st.services.engine.connect() as conn:
        return _json(gp.home(conn))


@router.get("/guide/cases/{key}", dependencies=[Depends(rate_limit("public"))],
            responses={404: {"description": "not found or not published"}})
def guide_case(key: str, st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import guides_public as gp

    if key not in {"1000", "2000", "4000"}:
        raise ApiError(404, "not_found", "unknown case")
    with st.services.engine.connect() as conn:
        page = gp.case_page(conn, key)
    if page is None:
        raise ApiError(404, "unpublished_object", "case guide not published")
    return _json(page)


@router.get("/guide/witnesses/{slug}", dependencies=[Depends(rate_limit("public"))],
            responses={404: {"description": "not found"}})
def guide_witness(slug: str, st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import guides_public as gp

    if not slug.startswith("w_") or len(slug) != 12:
        raise ApiError(404, "not_found", "unknown witness")
    with st.services.engine.connect() as conn:
        page = gp.witness_page(conn, slug)
    if page is None:
        raise ApiError(404, "not_found", "unknown witness")
    return _json(page)


@router.get("/guide/timeline", dependencies=[Depends(rate_limit("public"))])
def guide_timeline(st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import guides_public as gp

    with st.services.engine.connect() as conn:
        return _json(gp.timeline(conn))


@router.get("/glossary", dependencies=[Depends(rate_limit("public"))])
def glossary() -> JSONResponse:
    from ntk_common.glossary import glossary as g

    return _json(g(), cache="public, max-age=3600")


# ------------------------------------------------------------------ mirror sync (the site keeps its own copy)
@router.get("/sync/objects", dependencies=[Depends(rate_limit("public"))])
def sync_objects(st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import sync

    with st.services.engine.connect() as conn:
        return _json(sync.objects(conn), cache="no-store")


@router.get("/sync/changes", dependencies=[Depends(rate_limit("public"))])
def sync_changes(since: dt.datetime, st: AppState = Depends(get_state)) -> JSONResponse:
    from ntk_common.db import sync

    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.UTC)
    with st.services.engine.connect() as conn:
        return _json(sync.changes(conn, since), cache="no-store")
