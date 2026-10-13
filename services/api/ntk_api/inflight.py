"""One answer per question at a time (13.10.2026).

A defense-lens answer takes about a minute. A visitor who asks again — or a second visitor with the same question —
must wait for the answer being written, not start a second paid run. The first request holds a Redis key while it
answers; the others poll for the stored answer. Without Redis every request answers as before.
"""

from __future__ import annotations

import time

TTL_SECONDS = 240
WAIT_SECONDS = 80


def acquire(redis_client, lock: str | None) -> bool:
    """True when this request answers the question (or no lock applies), False when another request already is."""
    if not lock or redis_client is None:
        return True
    try:
        return bool(redis_client.set(lock, "1", nx=True, ex=TTL_SECONDS))
    except Exception:  # noqa: BLE001 — without Redis, answer as before
        return True


def release(redis_client, lock: str | None, owner: bool) -> None:
    if lock and owner is True and redis_client is not None:
        try:
            redis_client.delete(lock)
        except Exception:  # noqa: BLE001
            pass


def wait(redis_client, ask, question: str, locale: str, *, sleep=time.sleep, clock=time.monotonic):
    """The answer the other request stores, or None if it does not arrive within WAIT_SECONDS."""
    deadline = clock() + WAIT_SECONDS
    while clock() < deadline:
        sleep(2)
        res = ask.stored(question, locale=locale)
        if res is not None:
            return res
        try:
            if not redis_client.exists(ask.inflight_key(question, locale)):
                return ask.stored(question, locale=locale)
        except Exception:  # noqa: BLE001
            return None
    return None
