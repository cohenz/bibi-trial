"""Daily budget of new Ask answers (cost control, 13.10.2026).

Only an answer that needs the model counts: a stored answer, a refusal, a corrected premise or "no published
material" is free and never limited. Counters live in Redis per UTC day (in memory without Redis):

  ntk:ask:{day}:model          new answers (site-wide)       — capped by NTK_ASK_DAILY_LIMIT
  ntk:ask:{day}:v:{visitor}    new answers of one visitor    — capped by NTK_ASK_VISITOR_DAILY_LIMIT
  ntk:ask:{day}:{total|cached|free|limited}                  — for the usage report
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import defaultdict

from ntk_common.ask import AskLimited

TTL = 120 * 86400
_MEM: dict[str, int] = defaultdict(int)
_LOCK = threading.Lock()


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


class AskBudget:
    def __init__(self, redis_client, *, daily_limit: int, visitor_limit: int):
        self.redis = redis_client
        self.daily_limit = daily_limit
        self.visitor_limit = visitor_limit

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

    def reserve(self, visitor: str | None) -> None:
        """Called right before a new answer's first model call; raises AskLimited when a cap is reached."""
        day = _today()
        if self.daily_limit > 0 and self._get(f"ntk:ask:{day}:model") >= self.daily_limit:
            raise AskLimited("daily_limit")
        if visitor and self.visitor_limit > 0 and self._get(f"ntk:ask:{day}:v:{visitor}") >= self.visitor_limit:
            raise AskLimited("visitor_daily_limit")
        self._incr(f"ntk:ask:{day}:model")
        if visitor:
            self._incr(f"ntk:ask:{day}:v:{visitor}")

    def count(self, what: str) -> None:
        self._incr(f"ntk:ask:{_today()}:{what}")

    def counters(self, day: str) -> dict:
        return {k: self._get(f"ntk:ask:{day}:{k}") for k in ("total", "model", "cached", "free", "limited")}


MESSAGES = {
    "daily_limit": "הגענו למכסת השאלות החדשות להיום. שאלות שכבר נשאלו עדיין נענות, ואפשר לחפש בעמודי העדים, הדיונים והמסמכים. נסו שוב מחר.",
    "visitor_daily_limit": "שאלתם היום הרבה שאלות חדשות. שאלות שכבר נשאלו עדיין נענות; לשאלות חדשות נסו שוב מחר.",
}
