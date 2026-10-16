"""Search interface (spec §11, §29; ADR-0005).

``SearchBackend`` is the only thing the API and the answer engine depend on,
so an OpenSearch implementation can be added later without changing the
public API or the data contracts. V1 ships ``PostgresSearchBackend``.

Results are always SourceUnits (the citation unit); chunk hits are mapped
back to their member units (spec §29.2: "answer citations are chosen from
SourceUnits that are members of ranked chunks, not from the chunk").
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from .. import hebrew

RRF_K = 60
SIGNALS = ("exact", "terms", "trgm", "ngram", "vector", "graph")


@dataclass
class SearchFilters:
    case_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    witness: str | None = None
    phase: str | None = None
    court_record_status: list[str] | None = None
    hearing_id: str | None = None
    published_only: bool = True
    source_types: list[str] | None = None  # e.g. ["indictment"] (16.10.2026: the prosecution's claim from its source)


@dataclass
class SearchRequest:
    query: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    limit: int = 20
    signals: tuple[str, ...] = SIGNALS
    per_signal_limit: int = 60


@dataclass
class SearchHit:
    source_unit_id: str
    score: float
    signals: dict[str, int]  # signal → rank (1-based)
    page: int = 0
    line_start: int = 0
    line_end: int = 0
    speaker_label: str | None = None
    speaker_role: str | None = None
    unit_type: str | None = None
    examination_phase: str | None = None
    text: str = ""
    source_version_id: str = ""
    hearing_id: str | None = None
    hearing_date: str | None = None
    court_record_status: str = "unknown"
    chunk_ids: list[str] = field(default_factory=list)


@dataclass
class SearchResponse:
    query: str
    hits: list[SearchHit]
    signal_counts: dict[str, int]
    timings_ms: dict[str, float]
    backend: str


class SearchBackend(Protocol):
    name: str

    def search(self, req: SearchRequest) -> SearchResponse: ...


def rrf(rankings: dict[str, list[str]], k: int = RRF_K, weights: dict[str, float] | None = None) -> list[tuple[str, float, dict[str, int]]]:
    """Reciprocal Rank Fusion over per-signal ranked id lists."""
    weights = weights or {}
    scores: dict[str, float] = defaultdict(float)
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for signal, ids_ in rankings.items():
        w = weights.get(signal, 1.0)
        for r, uid in enumerate(ids_, start=1):
            if signal in ranks[uid]:
                continue
            scores[uid] += w / (k + r)
            ranks[uid][signal] = r
    return sorted(((u, s, ranks[u]) for u, s in scores.items()), key=lambda t: (-t[1], t[0]))


_EXACT_RE = re.compile(
    r"\d{4,5}-\d{2}-\d{2}"  # case numbers
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4}"  # dates
    r"|[נת]/\d+"  # exhibits
    r"|סעיף\s*\d+[א-ת]?"  # sections
)


def exact_terms(query: str) -> list[str]:
    """Identifiers that must match literally (case numbers, dates, exhibits,
    sections) plus quoted phrases."""
    q = hebrew.normalize(query)
    out = [m.group(0) for m in _EXACT_RE.finditer(q)]
    out += [m.group(1).strip() for m in re.finditer(r"[\"“”״]([^\"“”״]{2,80})[\"“”״]", query)]
    return list(dict.fromkeys(t for t in out if t))


def query_terms(query: str, aliases: dict[str, list[str]] | None = None) -> list[str]:
    stop = {"מה", "מי", "איך", "האם", "של", "את", "על", "עם", "זה", "אם", "כי", "לא", "כן", "גם", "או", "אל", "יש", "אין",
            "היה", "הוא", "היא", "הם", "למה", "מתי", "כמה", "איזה", "אילו", "באמת", "אמר", "אמרה"}
    return [t for t in hebrew.search_terms(query, aliases) if t not in stop and len(t) >= 2]
