"""RetrievalChunk construction, profile ``chunk-v1`` (spec §23.1, §27.2).

* chunks are built only from whole SourceUnits of one SourceVersion;
* target 300–1,200 tokens; a single unit larger than the maximum becomes its
  own chunk (it is still a whole unit);
* a question is never separated from the answer that follows it;
* the chunk id is ``stable_id("rc", [profile, ordered unit ids])`` so changing
  the profile creates new chunks without touching citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import hebrew, ids
from .protocol import UnitRecord

CHUNK_PROFILE = "chunk-v1"
MIN_TOKENS = 300
MAX_TOKENS = 1200
HARD_MAX_TOKENS = 2000  # schema limit


@dataclass
class ChunkRecord:
    id: str
    chunk_profile: str
    ordered_source_unit_ids: list[str]
    token_count: int
    raw_text: str
    normalized_text: str
    prefix_forms: list[str] = field(default_factory=list)
    char_ngrams: list[str] = field(default_factory=list)
    examination_phases: list[str] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)


def _unit_text(u: UnitRecord) -> str:
    # turns whose label sits on the same printed line already carry it in raw_text — don't repeat it
    if not u.speaker_label or u.raw_text.lstrip().startswith(u.speaker_label):
        return u.raw_text
    return f"{u.speaker_label}: {u.raw_text}"


def build_chunks(units: list[UnitRecord], *, profile: str = CHUNK_PROFILE, min_tokens: int = MIN_TOKENS,
                 max_tokens: int = MAX_TOKENS) -> list[ChunkRecord]:
    groups: list[list[UnitRecord]] = []
    cur: list[UnitRecord] = []
    cur_tokens = 0
    for idx, u in enumerate(units):
        t = hebrew.estimate_tokens(_unit_text(u))
        must_stay = bool(cur) and cur[-1].unit_type == "question" and u.unit_type == "answer"
        if cur and not must_stay and cur_tokens + t > max_tokens and cur_tokens >= min_tokens // 2:
            groups.append(cur)
            cur, cur_tokens = [], 0
        cur.append(u)
        cur_tokens += t
        nxt = units[idx + 1] if idx + 1 < len(units) else None
        q_pending = u.unit_type == "question" and nxt is not None and nxt.unit_type == "answer"
        if cur_tokens >= min_tokens and not q_pending and (nxt is None or cur_tokens + hebrew.estimate_tokens(_unit_text(nxt)) > max_tokens):
            groups.append(cur)
            cur, cur_tokens = [], 0
    if cur:
        if groups and cur_tokens < min_tokens // 2 and _tokens(groups[-1]) + cur_tokens <= max_tokens:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    chunks = []
    for g in groups:
        for sub in _enforce_hard_max(g):
            raw = "\n".join(_unit_text(u) for u in sub)
            norm = hebrew.normalize(raw)
            terms = hebrew.search_terms(norm)
            chunks.append(
                ChunkRecord(
                    id=ids.chunk_id(profile, [u.id for u in sub]),
                    chunk_profile=profile,
                    ordered_source_unit_ids=[u.id for u in sub],
                    token_count=min(HARD_MAX_TOKENS, max(1, hebrew.estimate_tokens(raw))),
                    raw_text=raw,
                    normalized_text=norm,
                    prefix_forms=terms,
                    char_ngrams=hebrew.char_ngrams(norm)[:4000],
                    examination_phases=sorted({u.examination_phase for u in sub}),
                    speakers=sorted({u.speaker_label for u in sub if u.speaker_label}),
                )
            )
    return chunks


def _tokens(group: list[UnitRecord]) -> int:
    return sum(hebrew.estimate_tokens(_unit_text(u)) for u in group)


def _enforce_hard_max(group: list[UnitRecord]) -> list[list[UnitRecord]]:
    out: list[list[UnitRecord]] = []
    cur: list[UnitRecord] = []
    tok = 0
    for u in group:
        t = hebrew.estimate_tokens(_unit_text(u))
        if cur and tok + t > HARD_MAX_TOKENS:
            out.append(cur)
            cur, tok = [], 0
        cur.append(u)
        tok += t
    if cur:
        out.append(cur)
    return out
