"""Deterministic identifiers.

Spec §27.4 / ADR-0002. Every identifier that can be recomputed from its
inputs is derived, never random, so that re-running the pipeline on the same
bytes with the same parser/prompt versions is idempotent.

``stable_id`` mirrors the SQL function ``ntk.stable_id(prefix, parts[])``:
sha256 over the parts joined by the ASCII unit separator (0x1F), hex, first
26 characters, prefixed. Tests assert that the Python and SQL versions agree.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

UNIT_SEP = "\x1f"
STABLE_ID_HEX_LEN = 26

# Namespace for UUIDv5 identifiers of derived objects (layer A/B/C rows,
# model runs, answers). Changing it would change every derived id: never do.
NTK_NAMESPACE = uuid.UUID("5a1e0f3c-7d2b-5b8e-9c4a-67104012020a")

KNOWN_PREFIXES = {
    "doc": "source document (logical)",
    "sv": "source version (immutable bytes)",
    "su": "source unit (citation unit)",
    "qx": "Q/A exchange",
    "rc": "retrieval chunk",
    "hr": "hearing",
    "ev315": "Project 315 event",
    "case": "court case",
}


def _part_to_text(part: Any) -> str:
    if part is None:
        return ""
    if isinstance(part, bool):
        return "1" if part else "0"
    if isinstance(part, (list, tuple)):
        return UNIT_SEP.join(_part_to_text(p) for p in part)
    return str(part)


def stable_id(prefix: str, parts: Sequence[Any]) -> str:
    """Return ``<prefix>_<26 hex>`` from sha256 of the joined parts."""
    if not prefix or not prefix.isascii() or not prefix.isalnum() or not prefix.islower() and not prefix.isdigit():
        raise ValueError(f"invalid stable_id prefix: {prefix!r}")
    joined = UNIT_SEP.join(_part_to_text(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:STABLE_ID_HEX_LEN]}"


def derived_uuid(kind: str, *parts: Any) -> uuid.UUID:
    """UUIDv5 for derived rows whose SQL type is ``uuid``.

    ``kind`` namespaces the object type ("claim", "model_run", ...)."""
    name = UNIT_SEP.join([kind, *(_part_to_text(p) for p in parts)])
    return uuid.uuid5(NTK_NAMESPACE, name)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: Any) -> str:
    """Hash of a canonical JSON encoding (sorted keys, no whitespace)."""
    import json

    return sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def normalize_speaker_label(label: str | None) -> str:
    """Speaker label as it participates in the SourceUnit id.

    Only whitespace, punctuation variants and Unicode form are normalised so
    that the id is robust to cosmetic extraction differences but still
    distinguishes different speakers. Text content is *not* part of the id
    (spec §27.4) so normalisation improvements never break citations.
    """
    if not label:
        return ""
    s = unicodedata.normalize("NFC", label)
    s = s.replace("״", '"').replace("׳", "'").replace("`", "'").replace("’", "'").replace("”", '"').replace("“", '"')
    s = s.strip().rstrip(":").strip()
    return " ".join(s.split())


def source_document_id(case_id: str, canonical_key: str) -> str:
    return stable_id("doc", [case_id, canonical_key])


def source_version_id(document_id: str, content_sha256: str) -> str:
    return stable_id("sv", [document_id, content_sha256])


def source_unit_id(
    source_version_id_: str, page: int, line_start: int, line_end: int, ordinal: int, speaker_label: str | None
) -> str:
    return stable_id(
        "su",
        [source_version_id_, page, line_start, line_end, ordinal, normalize_speaker_label(speaker_label)],
    )


def exchange_id(question_unit_id: str, answer_unit_id: str, parser_version: str) -> str:
    return stable_id("qx", [question_unit_id, answer_unit_id, parser_version])


def chunk_id(chunk_profile: str, ordered_source_unit_ids: Iterable[str]) -> str:
    return stable_id("rc", [chunk_profile, list(ordered_source_unit_ids)])


def hearing_id(case_id: str, hearing_date: str, source_version_id_: str) -> str:
    return stable_id("hr", [case_id, hearing_date, source_version_id_])


def case_id_for(court_case_number: str, court_code: str = "il-jdc-jerusalem") -> str:
    """Human-readable case id, e.g. ``il-jdc-jerusalem-67104-01-20``."""
    return f"{court_code}-{court_case_number}"
