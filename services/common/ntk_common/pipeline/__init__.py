"""Deterministic L0 pipeline: PDF → lines → turns → SourceUnits → exchanges → chunks.

Everything in this package is pure (no database, no network) so that each
stage is unit-testable and re-runnable; persistence and orchestration live
in ``ntk_common.db`` and ``ntk_worker``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .. import hebrew, ids
from .chunking import CHUNK_PROFILE, ChunkRecord, build_chunks
from .pdf import EXTRACTOR_VERSION, ExtractedDocument, extract_document, validate_pdf
from .protocol import PARSER_VERSION, ParsedProtocol, UnitRecord, parse_protocol
from .qa import PAIRER_VERSION, Exchange, pair_exchanges

PIPELINE_VERSION = f"{EXTRACTOR_VERSION}+{PARSER_VERSION}+{PAIRER_VERSION}+{CHUNK_PROFILE}"


@dataclass
class L0Result:
    source_version_id: str
    content_sha256: str
    page_count: int
    extracted: ExtractedDocument
    parsed: ParsedProtocol
    exchanges: list[Exchange]
    chunks: list[ChunkRecord]
    warnings: list[str] = field(default_factory=list)

    def source_unit_payload(self, u: UnitRecord, *, hearing_id: str | None, court_record_status: str,
                            created_at: str | None = None) -> dict:
        """SourceUnit contract payload (spec §26)."""
        return {
            "schema_version": "2.0",
            "id": u.id,
            "source_version_id": self.source_version_id,
            "hearing_id": hearing_id,
            "location": {"page": u.page, "line_start": u.line_start, "line_end": u.line_end, "ordinal": u.ordinal},
            "speaker": (
                {"label": u.speaker_label, "entity_id": None, "role": u.speaker_role} if u.speaker_label else None
            ),
            "examination_phase": u.examination_phase,
            "unit_type": u.unit_type,
            "text": u.raw_text,
            "normalized_text": hebrew.normalize(u.raw_text),
            "court_record_status": court_record_status,
            "turn_key": u.turn_key,
            "turn_part": u.turn_part,
            "synthetic_lines": u.synthetic_lines,
            "provenance": {
                "content_sha256": self.content_sha256,
                "parser_version": PARSER_VERSION,
                "created_at": created_at or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            },
        }


def run_l0(data: bytes, *, document_id: str, allow_ocr: bool = True, expected_sha256: str | None = None,
           declared_mime: str | None = "application/pdf", case_number_hint: str | None = None) -> L0Result:
    facts = validate_pdf(data, declared_mime=declared_mime, expected_sha256=expected_sha256)
    svid = ids.source_version_id(document_id, facts["content_sha256"])
    extracted = extract_document(data, allow_ocr=allow_ocr)
    lines = [ln for p in extracted.pages for ln in p.lines]
    parsed = parse_protocol(lines, source_version_id=svid, case_number_hint=case_number_hint)
    exchanges, pw = pair_exchanges(parsed.units)
    chunks = build_chunks(parsed.units)
    return L0Result(
        source_version_id=svid,
        content_sha256=facts["content_sha256"],
        page_count=facts["page_count"],
        extracted=extracted,
        parsed=parsed,
        exchanges=exchanges,
        chunks=chunks,
        warnings=[*extracted.warnings, *parsed.warnings, *pw],
    )


__all__ = [
    "L0Result", "run_l0", "PIPELINE_VERSION", "PARSER_VERSION", "CHUNK_PROFILE", "UnitRecord", "Exchange", "ChunkRecord",
]
