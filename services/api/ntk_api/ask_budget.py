"""Daily budget of new Ask answers (cost control, 13.10.2026).

Only an answer that needs the model counts: a stored answer, a refusal, a corrected premise or "no published
material" is free and never limited. Counters live in Redis per UTC day (in memory without Redis):

  ntk:ask:{day}:model          new answers (site-wide)       — capped by NTK_ASK_DAILY_LIMIT
  ntk:ask:{day}:v:{visitor}    new answers of one visitor    — capped by NTK_ASK_VISITOR_DAILY_LIMIT
  ntk:ask:{day}:{total|cached|free|limited}                  — for the usage report

The caps are set in Railway (NTK_ASK_*), and the site's admin can override them from WordPress (13.10.2026):
the overrides live in the Redis hash ntk:ask:limits (daily, per_visitor_daily, per_minute); a missing field falls
back to the Railway value.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import defaultdict

from ntk_common.ask import AskLimited

TTL = 120 * 86400
_MEM: dict[str, int] = defaultdict(int)
_LOCK = threading.Lock()


LIMITS_KEY = "ntk:ask:limits"
LIMIT_FIELDS = {"daily": (0, 100000), "per_visitor_daily": (0, 10000), "per_minute": (1, 600)}


def _overrides(redis_client) -> dict[str, int]:
    if redis_client is None:
        with _LOCK:
            return dict(_MEM_LIMITS)
    try:
        raw = redis_client.hgetall(LIMITS_KEY) or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else str(k)
        try:
            if k in LIMIT_FIELDS:
                out[k] = int(v)
        except (TypeError, ValueError):
            continue
    return out


_MEM_LIMITS: dict[str, int] = {}


def effective_limits(redis_client, settings) -> dict:
    """The caps in force: the admin's overrides over the Railway values. ``source`` names where each one came from."""
    base = {"daily": settings.ask_daily_limit, "per_visitor_daily": settings.ask_visitor_daily_limit,
            "per_minute": settings.rate_limit_ask_per_minute}
    over = _overrides(redis_client)
    return {**base, **over, "railway": base, "source": {k: ("admin" if k in over else "railway") for k in base}}


def set_limits(redis_client, values: dict) -> dict:
    """Set (an int) or clear (None) each given cap; values outside the allowed range raise ValueError."""
    for k, v in values.items():
        if k not in LIMIT_FIELDS:
            raise ValueError(f"unknown limit {k}")
        if v is not None:
            lo, hi = LIMIT_FIELDS[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValueError(f"{k} must be an integer between {lo} and {hi}")
    for k, v in values.items():
        if redis_client is None:
            with _LOCK:
                if v is None:
                    _MEM_LIMITS.pop(k, None)
                else:
                    _MEM_LIMITS[k] = v
        elif v is None:
            redis_client.hdel(LIMITS_KEY, k)
        else:
            redis_client.hset(LIMITS_KEY, k, v)
    return _overrides(redis_client)


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


class AskBudget:
    def __init__(self, redis_client, *, daily_limit: int, visitor_limit: int):
        self.redis = redis_client
        self.daily_limit = daily_limit
        self.visitor_limit = visitor_limit

    @classmethod
    def from_settings(cls, redis_client, settings) -> AskBudget:
        lim = effective_limits(redis_client, settings)
        return cls(redis_client, daily_limit=lim["daily"], visitor_limit=lim["per_visitor_daily"])

    def _get(self, k: str) -> int:
        if self.redis is not None:
            try:
                return int(self.redis.get(k) or 0)
            except Exception:  # noqa: BLE001
                pass
        with _LOCK:
            return _MEM.get(k, 0)

    def _incr(self, k: str) -> int:
        if self.redis is not None:
            try:
                pipe = self.redis.pipeline()
                pipe.incr(k)
                pipe.expire(k, TTL)
                return int(pipe.execute()[0])
            except Exception:  # noqa: BLE001
                pass
        with _LOCK:
            _MEM[k] += 1
            return _MEM[k]

    def _decr(self, k: str) -> None:
        if self.redis is not None:
            try:
                self.redis.decr(k)
                return
            except Exception:  # noqa: BLE001
                pass
        with _LOCK:
            _MEM[k] -= 1

    def reserve(self, visitor: str | None) -> None:
        """Called right before a new answer's first model call; raises AskLimited when a cap is reached."""
        day = _today()
        # increment first, then compare: simultaneous requests cannot slip past the cap together
        if visitor and self.visitor_limit > 0 and self._incr(f"ntk:ask:{day}:v:{visitor}") > self.visitor_limit:
            self._decr(f"ntk:ask:{day}:v:{visitor}")
            raise AskLimited("visitor_daily_limit")
        if self.daily_limit > 0 and self._incr(f"ntk:ask:{day}:model") > self.daily_limit:
            self._decr(f"ntk:ask:{day}:model")
            if visitor and self.visitor_limit > 0:
                self._decr(f"ntk:ask:{day}:v:{visitor}")
            raise AskLimited("daily_limit")
        if self.daily_limit <= 0:
            self._incr(f"ntk:ask:{day}:model")

    def count(self, what: str) -> None:
        self._incr(f"ntk:ask:{_today()}:{what}")

    def counters(self, day: str) -> dict:
        return {k: self._get(f"ntk:ask:{day}:{k}") for k in ("total", "model", "cached", "free", "limited")}


MESSAGES = {
    "daily_limit": "הגענו למכסת השאלות החדשות להיום. שאלות שכבר נשאלו עדיין נענות, ואפשר לחפש בעמודי העדים, הדיונים והמסמכים. נסו שוב מחר.",
    "visitor_daily_limit": "שאלתם היום הרבה שאלות חדשות. שאלות שכבר נשאלו עדיין נענות; לשאלות חדשות נסו שוב מחר.",
}
