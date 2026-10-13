"""Knowledge API (FastAPI). Spec §14, §32, §33; build brief "Knowledge API".

Public endpoints return only published objects. Admin endpoints require a
signed service-account request with explicit scopes, and every admin action
writes an audit event.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ntk_common.ask import AskConfig, AskEngine
from ntk_common.config import Settings, get_settings
from ntk_common.db.core import get_engine
from ntk_common.db.public import PgAskStore
from ntk_common.jobs import CeleryQueue, JobQueue
from ntk_common.orchestrator import Services, build_services
from starlette.exceptions import HTTPException as StarletteHTTPException

from .security import NonceStore, RateLimiter

log = logging.getLogger("ntk.api")
API_VERSION = "2.1.0"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


@dataclass
class AppState:
    settings: Settings
    services: Services
    queue: JobQueue
    nonces: NonceStore
    limiter: RateLimiter
    ask: AskEngine
    redis: Any = None


def _redis(url: str):
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        log.warning("Redis unavailable; using in-memory rate limits and nonces (single instance only)")
        return None


def build_state(settings: Settings, *, queue: JobQueue | None = None, services: Services | None = None,
                redis_client: Any = "auto") -> AppState:
    engine = get_engine(settings.database_url)
    services = services or build_services(settings, engine)
    r = _redis(settings.redis_url) if redis_client == "auto" else redis_client
    ask = AskEngine(PgAskStore(engine, case_id=settings.case_id), services.search_backend(), services.runner,
                    AskConfig(answer_base=settings.answer_base, citation_base=settings.citation_base,
                              max_question_chars=settings.max_question_chars, env=settings.env,
                              independent_verifier=not services.registry.single_family,
                              thinking=settings.ask_thinking, verify_thinking=settings.ask_verify_thinking))
    return AppState(settings=settings, services=services, queue=queue or CeleryQueue(settings.redis_url),
                    nonces=NonceStore(r), limiter=RateLimiter(r), ask=ask, redis=r)


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "ntk", None) is None:
            app.state.ntk = build_state(get_settings())
        yield

    app = FastAPI(
        title="Netanyahu Trial Knowledge API",
        version=API_VERSION,
        description=(
            "Public, citation-first API over the official protocols of criminal case 67104-01-20. "
            "Public endpoints return published objects only. Admin endpoints require a signed service-account "
            "request (headers X-NTK-Key-Id, X-NTK-Timestamp, X-NTK-Nonce, X-NTK-Actor, X-NTK-Signature; see ADR-0004)."
        ),
        lifespan=lifespan,
        responses={400: {"model": None}},
    )
    if state is not None:
        app.state.ntk = state

    settings = state.settings if state else get_settings()
    if settings.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type"], max_age=600)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid[:64]
        st: AppState = request.app.state.ntk
        cl = request.headers.get("content-length")
        limit = st.settings.max_body_bytes if not request.url.path.startswith("/v2/admin/project315") else 20 * 1024 * 1024
        if cl and cl.isdigit() and int(cl) > limit:
            return _error(413, "payload_too_large", f"body exceeds {limit} bytes", rid)
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, (time.perf_counter() - t0) * 1000)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(exc.status, exc.code, str(exc), _rid(request), exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return _error(400, "invalid_request", "request validation failed", _rid(request), details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "invalid_request", 401: "unauthorized", 403: "forbidden"}.get(exc.status_code, "invalid_request")
        return _error(exc.status_code, code, str(exc.detail), _rid(request))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal_error", "internal error", _rid(request))

    from .routers import admin, public

    app.include_router(public.router)
    app.include_router(admin.router)

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        from .schemas import ErrorEnvelope

        spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        comps = spec.setdefault("components", {})
        schemas = comps.setdefault("schemas", {})
        schemas["ErrorEnvelope"] = ErrorEnvelope.model_json_schema()
        comps["securitySchemes"] = {
            "ServiceKeyId": {"type": "apiKey", "in": "header", "name": "X-NTK-Key-Id"},
            "ServiceTimestamp": {"type": "apiKey", "in": "header", "name": "X-NTK-Timestamp"},
            "ServiceNonce": {"type": "apiKey", "in": "header", "name": "X-NTK-Nonce"},
            "ServiceActor": {"type": "apiKey", "in": "header", "name": "X-NTK-Actor"},
            "ServiceSignature": {"type": "apiKey", "in": "header", "name": "X-NTK-Signature",
                                 "description": "hex HMAC-SHA256(secret, METHOD\\nPATH\\nsorted-query\\ntimestamp\\nnonce\\nactor\\nsha256(body))"},
        }
        err = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                                                "example": {"code": "invalid_request", "message": "request validation failed",
                                                            "request_id": "3f2a…", "details": None}}}}
        codes = {"400": "invalid_request / unsupported_schema", "401": "unauthorized", "403": "forbidden",
                 "404": "not_found / unpublished_object", "409": "conflict / review_required / unpublished_object",
                 "413": "payload_too_large", "422": "citation_gate_failed", "429": "rate_limited", "500": "internal_error"}
        for path, item in spec["paths"].items():
            for method, op in item.items():
                for code, desc in codes.items():
                    if code in {"401", "403"} and not path.startswith("/v2/admin"):
                        continue
                    op.setdefault("responses", {}).setdefault(code, {"description": desc, **err})
                op["responses"].pop("422", None) if "422" in op["responses"] and "citation_gate_failed" not in str(op["responses"]["422"]) else None
                op["responses"].setdefault("422", {"description": "citation_gate_failed", **err}) if path.startswith("/v2/admin") else None
                if path.startswith("/v2/admin"):
                    op["security"] = [{"ServiceKeyId": [], "ServiceTimestamp": [], "ServiceNonce": [], "ServiceActor": [],
                                       "ServiceSignature": []}]
        app.openapi_schema = spec
        return spec

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "") or uuid.uuid4().hex


def _error(status: int, code: str, message: str, rid: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "request_id": rid, "details": details})


app = create_app()
