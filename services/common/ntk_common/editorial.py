"""House style for text the models wrote, applied when it is served (never to source text or quotes).

* "היענות חריגה" alone is the indictment's shorthand; readers who do not know the case need the whole term,
  "היענות חריגה לדרישות סיקור" (13.10.2026). "ההיענות חריגה" (a predicate: "the responsiveness was exceptional") and a
  phrase that already names the demands nearby are left as written.

Applied at read time so stored artifacts, their hashes and the model-answer cache stay as they are; the same rule
runs on every guide, digest, brief and answer, old or new.
"""

from __future__ import annotations

import re
from typing import Any

_EXCEPTIONAL = re.compile(r"(?<![א-ת])([ובלכמש]{0,2})היענות\s+חריגה(?!\s+(?:\S+\s+){0,4}?לדרישו?ת)")
FULL_TERM = "היענות חריגה לדרישות סיקור"

# generated prose fields; never "quote", unit text, speaker labels or ids
TEXT_KEYS = frozenset({"text", "summary", "title", "label", "long", "short", "one_line", "subtitle", "display_title",
                       "description", "answer_short", "about", "claim_text", "body"})


def polish_text(s: str) -> str:
    if not s or "חריגה" not in s:
        return s
    return _EXCEPTIONAL.sub(lambda m: m.group(1) + FULL_TERM, s)


def polish(obj: Any, *, _key: str | None = None) -> Any:
    """A copy of a generated payload (dicts/lists) with house style applied to its prose fields."""
    if isinstance(obj, dict):
        return {k: polish(v, _key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [polish(v, _key=_key) for v in obj]
    if isinstance(obj, str) and _key in TEXT_KEYS:
        return polish_text(obj)
    return obj
