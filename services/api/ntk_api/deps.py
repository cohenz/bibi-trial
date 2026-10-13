from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from .app import ApiError, AppState
from .security import AuthError, Principal, ip_hash, verify_request


def get_state(request: Request) -> AppState:
    return request.app.state.ntk


def client_ip(request: Request) -> str:
    """The peer address as seen by our edge. Railway's proxy appends the real
    peer to X-Forwarded-For, so the *rightmost* entry is trustworthy; leftmost
    entries are client-controlled and are ignored."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def forwarded_client(request: Request, st: AppState) -> tuple[str, str] | None:
    """A trusted front end (WordPress) may vouch for the end user's identity:
    X-NTK-Key-Id, X-NTK-Client-Hash, X-NTK-Client-Ts and
    X-NTK-Client-Sig = hex HMAC-SHA256(secret, ts + "\n" + client_hash).
    Returns (key_id, client_hash) when valid."""
    import hashlib
    import hmac
    import time

    key_id = request.headers.get("x-ntk-key-id", "")
    ch = request.headers.get("x-ntk-client-hash", "")
    ts = request.headers.get("x-ntk-client-ts", "")
    sig = request.headers.get("x-ntk-client-sig", "")
    entry = st.settings.service_keys.get(key_id) if key_id else None
    if not (entry and ch and ts.isdigit() and sig) or len(ch) > 64:
        return None
    if abs(time.time() - int(ts)) > st.settings.signature_max_skew_seconds:
        return None
    expected = hmac.new(entry["secret"].encode(), f"{ts}\n{ch}".encode(), hashlib.sha256).hexdigest()
    return (key_id, ch) if hmac.compare_digest(expected, sig.lower()) else None


def rate_limit(bucket: str) -> Callable:
    """Per-client, per-session and per-front-end-key limits, with separate
    thresholds for ask and search (spec §33.2)."""

    def dep(request: Request, st: AppState = Depends(get_state)) -> None:
        if bucket == "ask":
            from .ask_budget import effective_limits
            ask_limit = effective_limits(st.redis, st.settings)["per_minute"]
        else:
            ask_limit = st.settings.rate_limit_ask_per_minute
        limit = {
            "ask": ask_limit,
            "search": st.settings.rate_limit_search_per_minute,
        }.get(bucket, st.settings.rate_limit_public_per_minute)
        fwd = forwarded_client(request, st)
        if fwd:
            key_id, ident = fwd
            ok_key, _ = st.limiter.hit(bucket + ":key", key_id, limit * 200)
        else:
            ident = ip_hash(client_ip(request), st.settings.ip_hash_salt or "ntk")
            ok_key = True
        ok, _ = st.limiter.hit(bucket, ident, limit)
        session = request.headers.get("x-ntk-session", "")[:64]
        if ok and session:
            ok, _ = st.limiter.hit(bucket + ":session", session, limit)
        if not (ok and ok_key):
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
