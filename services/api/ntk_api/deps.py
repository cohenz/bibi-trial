from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from .app import ApiError, AppState
from .security import AuthError, Principal, ip_hash, verify_request


def get_state(request: Request) -> AppState:
    return request.app.state.ntk


def client_ip(request: Request) -> str:
    # Railway/Cloudflare put the client address in X-Forwarded-For; use the first hop
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown"))[:64]


def rate_limit(bucket: str) -> Callable:
    def dep(request: Request, st: AppState = Depends(get_state)) -> None:
        limit = {
            "ask": st.settings.rate_limit_ask_per_minute,
            "search": st.settings.rate_limit_search_per_minute,
        }.get(bucket, st.settings.rate_limit_public_per_minute)
        ident = ip_hash(client_ip(request), st.settings.ip_hash_salt or "ntk")
        session = request.headers.get("x-ntk-session", "")[:64]
        ok, _ = st.limiter.hit(bucket, ident, limit)
        if ok and session:
            ok, _ = st.limiter.hit(bucket + ":session", session, limit)
        if not ok:
            raise ApiError(429, "rate_limited", f"rate limit exceeded for {bucket}; try again in a minute")
        request.state.ip_hash = ident

    return dep


def admin(scope: str) -> Callable:
    async def dep(request: Request, st: AppState = Depends(get_state)) -> Principal:
        body = await request.body()
        try:
            p = verify_request(keys=st.settings.service_keys, headers=dict(request.headers), method=request.method,
                               path=request.url.path, query=request.url.query, body=body, nonces=st.nonces,
                               max_skew=st.settings.signature_max_skew_seconds)
        except AuthError as exc:
            raise ApiError(exc.status, exc.code, str(exc)) from exc
        if not p.has(scope):
            raise ApiError(403, "forbidden", f"scope {scope} required")
        request.state.principal = p
        return p

    return dep
