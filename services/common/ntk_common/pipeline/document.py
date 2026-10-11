"""Citation units for court-file documents that are not hearing protocols.

Decisions, motions, responses, notices, affidavits and the like have no
speakers or Q/A. Their citation unit is the paragraph: consecutive body lines
on one page, split where the vertical gap between lines is clearly larger than
the page's usual line spacing, or where a numbered/lettered paragraph starts.
Units never cross pages and never exceed MAX_UNIT_CHARS (longer paragraphs are
split on line boundaries), so every citation is a page + line range.

The output reuses ``ParsedProtocol``/``UnitRecord`` so chunking, storage and
search treat these documents exactly like protocols. Decisions are attributed
to the court (unit_type ``decision``); a decision's *legal weight* is still not
assumed — judicial wording gates require a human-approved judicial level.
"""

from __future__ import annotations

import re
import statistics

from .. import ids
from .pdf import Line
from .protocol import PARSER_VERSION, ParsedProtocol, ProtocolHeader, UnitRecord

DOCUMENT_PARSER_VERSION = f"{PARSER_VERSION}+doc-1"
MAX_UNIT_CHARS = 1800
_ENUM_RE = re.compile(r"^\s*(?:\(?\d{1,3}[.)]|\(?[א-ת][.)]|[•\-–])\s+")

COURT_TYPES = {"decision"}


def _paragraphs(lines: list[Line]) -> list[list[Line]]:
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        if ln.kind == "body" and ln.text.strip():
            by_page.setdefault(ln.page, []).append(ln)
    out: list[list[Line]] = []
    for page in sorted(by_page):
        pl = sorted(by_page[page], key=lambda ln: (ln.top, ln.line_no))
        gaps = [b.top - a.top for a, b in zip(pl, pl[1:]) if b.top > a.top]
        typical = statistics.median(gaps) if gaps else 0.0
        cur: list[Line] = []
        for i, ln in enumerate(pl):
            gap = ln.top - pl[i - 1].top if i else 0.0
            new_par = bool(cur) and (
                (typical > 0 and gap > typical * 1.6) or bool(_ENUM_RE.match(ln.text))
                or sum(len(x.text) for x in cur) + len(ln.text) > MAX_UNIT_CHARS
            )
            if new_par:
                out.append(cur)
                cur = []
            cur.append(ln)
        if cur:
            out.append(cur)
    return out


def parse_document(lines: list[Line], *, source_version_id: str, source_type: str) -> ParsedProtocol:
    court = source_type in COURT_TYPES
    label = "בית המשפט" if court else None
    role = "court" if court else None
    unit_type = "decision" if court else "other"
    units: list[UnitRecord] = []
    for ordinal, par in enumerate(_paragraphs(lines)):
        text = "\n".join(ln.text for ln in par).strip()
        page = par[0].page
        ls = max(1, min(ln.line_no for ln in par))
        le = max(ls, max(ln.line_no for ln in par))
        units.append(UnitRecord(
            id=ids.source_unit_id(source_version_id, page, ls, le, ordinal, label),
            ordinal=ordinal, page=page, line_start=ls, line_end=le, speaker_label=label, speaker_role=role,
            speaker_side="court" if court else None, unit_type=unit_type, examination_phase="unknown", raw_text=text,
            turn_key=ids.stable_id("tk", [source_version_id, f"par-{ordinal}"]), turn_part=0, witness_label=None,
            synthetic_lines=any(ln.synthetic for ln in par), flags=[f"document:{source_type}"],
        ))
    warnings = [] if units else ["no text units found (scanned without OCR?)"]
    return ParsedProtocol(header=ProtocolHeader(), turns=[], units=units, witnesses=[], warnings=warnings,
                          parser_version=DOCUMENT_PARSER_VERSION)
