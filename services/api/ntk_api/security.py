"""Service-account request signing (ADR-0004) and rate limiting.

Admin calls carry:
  X-NTK-Key-Id      service account id (configured in NTK_SERVICE_KEYS)
  X-NTK-Timestamp   unix seconds; must be within NTK_SIGNATURE_MAX_SKEW_SECONDS
  X-NTK-Nonce       random, single use (replay protection)
  X-NTK-Actor       end user on whose behalf the call is made (e.g. WP login)
  X-NTK-Signature   hex HMAC-SHA256(secret, canonical_string)

canonical_string = METHOD \n PATH \n sorted-query \n timestamp \n nonce \n actor \n sha256(body)

The same canonicalisation is implemented by the WordPress plugin
(class-api-client.php); tests/unit/test_signing.py pins both to a vector.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

SCOPES = {"admin:read", "admin:ingest", "admin:review", "admin:publish", "admin:claims", "admin:all"}


def canonical_string(method: str, path: str, query: str, timestamp: str, nonce: str, actor: str, body: bytes) -> str:
    q = urlencode(sorted(parse_qsl(query or "", keep_blank_values=True)))
    return "\n".join([method.upper(), path, q, timestamp, nonce, actor, hashlib.sha256(body or b"").hexdigest()])


def sign(secret: str, *args) -> str:
    return hmac.new(secret.encode(), canonical_string(*args).encode(), hashlib.sha256).hexdigest()


@dataclass
class Principal:
    key_id: str
    actor: str
    scopes: set[str]

    def has(self, scope: str) -> bool:
        return "admin:all" in self.scopes or scope in self.scopes

    @property
    def label(self) -> str:
        return f"{self.key_id}:{self.actor}" if self.actor else self.key_id


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.status = status


class NonceStore:
    """Redis-backed single-use nonces with an in-memory fallback."""

    def __init__(self, redis_client=None, ttl: int = 900):
        self.redis = redis_client
        self.ttl = ttl
        self._mem: dict[str, float] = {}
        self._lock = threading.Lock()

    def use(self, key_id: str, nonce: str) -> bool:
        k = f"ntk:nonce:{key_id}:{nonce}"
        if self.redis is not None:
            try:
                return bool(self.redis.set(k, "1", nx=True, ex=self.ttl))
            except Exception:  # noqa: BLE001 - fall back if Redis is down
                pass
        now = time.time()
        with self._lock:
            for kk in [x for x, exp in self._mem.items() if exp < now]:
                self._mem.pop(kk, None)
            if k in self._mem:
                return False
            self._mem[k] = now + self.ttl
            return True


def verify_request(*, keys: dict, headers: dict, method: str, path: str, query: str, body: bytes,
                   nonces: NonceStore, max_skew: int, now: float | None = None) -> Principal:
    h = {k.lower(): v for k, v in headers.items()}
    key_id = h.get("x-ntk-key-id", "")
    ts = h.get("x-ntk-timestamp", "")
    nonce = h.get("x-ntk-nonce", "")
    actor = h.get("x-ntk-actor", "")
    sig = h.get("x-ntk-signature", "")
    if not (key_id and ts and nonce and sig):
        raise AuthError("unauthorized", "missing signature headers")
    entry = keys.get(key_id)
    if not entry or not entry.get("secret"):
        raise AuthError("unauthorized", "unknown key id")
    try:
        ts_i = int(ts)
    except ValueError as exc:
        raise AuthError("unauthorized", "invalid timestamp") from exc
    if abs((now or time.time()) - ts_i) > max_skew:
        raise AuthError("unauthorized", "timestamp outside allowed skew")
    if not (8 <= len(nonce) <= 128):
        raise AuthError("unauthorized", "invalid nonce")
    expected = sign(entry["secret"], method, path, query, ts, nonce, actor, body)
    if not hmac.compare_digest(expected, sig.lower()):
        raise AuthError("unauthorized", "bad signature")
    if not nonces.use(key_id, nonce):
        raise AuthError("unauthorized", "nonce already used")
    scopes = set(entry.get("scopes") or [])
    return Principal(key_id=key_id, actor=actor[:200], scopes=scopes)


class RateLimiter:
    """Fixed-window counters (per minute) in Redis, in-memory fallback."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._mem: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def hit(self, bucket: str, ident: str, limit: int, window: int = 60) -> tuple[bool, int]:
        slot = int(time.time() // window)
        k = f"ntk:rl:{bucket}:{ident}:{slot}"
        if self.redis is not None:
            try:
                pipe = self.redis.pipeline()
                pipe.incr(k)
                pipe.expire(k, window + 5)
                count = int(pipe.execute()[0])
                return count <= limit, max(0, limit - count)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._mem[k] += 1
            if len(self._mem) > 50000:
                self._mem.clear()
            count = self._mem[k]
        return count <= limit, max(0, limit - count)


def ip_hash(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]
