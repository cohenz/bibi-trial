"""Field mapping from a Project 315 export to the canonical event record.

No final mapping for the real export is invented here (build brief): the
real column names are unknown until a sample is provided. The adapter
accepts:

1. a *canonical snapshot*: records whose keys are already the canonical
   names below (``CANONICAL_FIELDS``); or
2. any JSON/CSV export plus a mapping file
   ``{"canonical_field": "source column name" | ["col a", "col b"]}``.

docs/project315-adapter.md lists exactly what a sample must contain to
complete the mapping.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

PARSER_VERSION = "p315-adapter-1.0"

CANONICAL_FIELDS = [
    "event_315_id", "indictment_reference", "date_or_range", "requester", "recipient", "subject", "description",
    "requested_action", "prosecution_description", "project315_classification", "project315_reasoning_summary",
    "netanyahu_involvement", "persons", "original_article_urls", "wayback_urls", "project315_page_url",
    "court_mentions", "witness_mentions",
]
REQUIRED = ["event_315_id", "project315_page_url", "project315_classification"]
INVOLVEMENT = {"direct", "inferred", "staff", "third_party", "unknown"}

IDENTITY_MAPPING: dict[str, str | list[str]] = {f: f for f in CANONICAL_FIELDS}


def apply_mapping(raw: dict, mapping: dict[str, str | list[str]] | None) -> dict:
    mapping = mapping or IDENTITY_MAPPING
    out: dict[str, Any] = {}
    for field, src in mapping.items():
        if isinstance(src, list):
            vals = [raw.get(s) for s in src if raw.get(s) not in (None, "")]
            out[field] = vals if field.endswith(("_urls", "_mentions")) or field == "persons" else (" ".join(map(str, vals)) or None)
        else:
            out[field] = raw.get(src)
    return out


def as_list(v: Any) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[\n;|]+", v) if x.strip()]
    return [v]


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y")


def parse_date(s: str) -> dt.date | None:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_date_or_range(v: Any) -> tuple[dict | None, str | None]:
    """Returns ({from,to,raw}, warning)."""
    if v in (None, ""):
        return None, None
    if isinstance(v, dict) and "from" in v:
        f = parse_date(str(v["from"]))
        t = parse_date(str(v["to"])) if v.get("to") else None
        if f is None:
            return None, f"unparseable date {v!r}"
        return {"from": f.isoformat(), "to": t.isoformat() if t else None, "raw": str(v.get("raw") or "")}, None
    s = str(v)
    # range separators: a spaced hyphen, en/em dash, or "עד" — never the hyphens inside an ISO date
    parts = [p for p in re.split(r"\s+(?:-{1,2}|עד)\s+|\s*[–—]\s*", s) if p.strip()]
    if len(parts) == 2:
        f, t = parse_date(parts[0]), parse_date(parts[1])
        if f and t:
            return {"from": f.isoformat(), "to": t.isoformat(), "raw": s}, None
    d = parse_date(s)
    if d:
        return {"from": d.isoformat(), "to": None, "raw": s}, None
    return None, f"unparseable date {s!r}"


def valid_url(u: str) -> bool:
    return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", u or ""))
