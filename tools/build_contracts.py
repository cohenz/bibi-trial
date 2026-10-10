"""Generate contracts/ntk-contracts-2.0.json (JSON Schema Draft 2020-12).

The spec (§26) defines Citation, SourceUnit, HearingDigest, ClaimBundle,
EvidencePoint, Review and AnswerEnvelope verbatim; those are reproduced here
unchanged except for the additive, optional fields listed in ADR-0010.
All other objects required by the build brief are defined in the same style.

Run:  python tools/build_contracts.py          (writes the file)
      python tools/build_contracts.py --check  (fails if the file is stale)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "contracts" / "ntk-contracts-2.0.json"

SV = "2.0"
CRS = ["filed", "admitted", "marked_for_identification", "referenced_in_court", "excluded", "not_filed", "external", "unknown"]
REVIEW_STATES = ["draft", "machine_verified", "human_review_required", "approved", "rejected", "published", "superseded"]
CLAIM_STATUS = [
    "unverified", "source_backed", "multi_source_supported", "court_recognized", "court_determined",
    "disputed", "partially_supported", "weakened", "rejected", "pending", "superseded",
]
JUDICIAL_LEVELS = ["question_or_comment", "interim_observation", "procedural_decision", "substantive_ruling"]
PHASES = ["preliminary", "direct", "cross", "redirect", "recross", "court_questions", "argument", "unknown"]
ANSWER_REL = ["affirms", "qualified_affirmation", "denies", "does_not_know", "nonresponsive", "ambiguous"]
OUTCOMES = ["verdict", "plea_deal", "withdrawal", "dismissal", "pardon_granted", "pardon_denied", "stay", "mistrial", "other"]
SOURCE_TYPES = ["indictment", "protocol", "decision", "motion", "exhibit", "article", "recording", "regulatory", "project315", "other"]
DIRECTIONS = ["supports", "weakens", "contextual", "neutral"]
VERIFICATION_315 = ["unreviewed", "source_checked", "transcript_confirmed", "contradicted", "inconclusive"]
INVOLVEMENT = ["direct", "inferred", "staff", "third_party", "unknown"]
JOB_STATUS = ["queued", "running", "succeeded", "failed", "cancelled"]
STAGES = [
    "register", "download", "validate", "extract_text", "ocr_fallback", "lineize", "segment", "pair", "chunk",
    "embed", "extract_a", "map_b", "verify", "review", "publish",
]
MODEL_ROLES = ["extractor", "mapper", "judicial_classifier", "verifier", "writer", "qa_relation", "embedder"]

SU_ID = "^su_[0-9a-f]{26}$"
SV_ID = "^sv_[0-9a-f]{26}$"
DOC_ID = "^doc_[0-9a-f]{26}$"
QX_ID = "^qx_[0-9a-f]{26}$"
RC_ID = "^rc_[0-9a-f]{26}$"
HR_ID = "^hr_[0-9a-f]{26}$"
SHA = "^[0-9a-f]{64}$"


def ref(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}"}


def nullable(t: str | list, **extra) -> dict:
    types = [t] if isinstance(t, str) else list(t)
    return {"type": [*types, "null"], **extra}


def obj(required: list[str], properties: dict, **extra) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties, **extra}


def arr(items: dict, **extra) -> dict:
    return {"type": "array", "items": items, **extra}


STR = {"type": "string"}
NESTR = {"type": "string", "minLength": 1}
DT = {"type": "string", "format": "date-time"}
DATE = {"type": "string", "format": "date"}
UUID = {"type": "string", "format": "uuid"}
CONF = {"type": "number", "minimum": 0, "maximum": 1}
CRS_REF = {"$ref": "#/$defs/Citation/properties/court_record_status"}

defs: dict[str, dict] = {}

# --- spec §26, verbatim ------------------------------------------------------
defs["Citation"] = obj(
    ["source_unit_id", "source_version_id", "page", "line_start", "line_end", "permalink"],
    {
        "source_unit_id": {"type": "string", "pattern": SU_ID},
        "source_version_id": {"type": "string", "pattern": SV_ID},
        "page": {"type": "integer", "minimum": 1},
        "line_start": {"type": "integer", "minimum": 1},
        "line_end": {"type": "integer", "minimum": 1},
        "speaker": nullable("string"),
        "quote": nullable("string"),
        "court_record_status": {"enum": CRS},
        "permalink": {"type": "string", "format": "uri"},
    },
)
defs["SourceUnit"] = obj(
    ["schema_version", "id", "source_version_id", "location", "unit_type", "text", "provenance"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": SU_ID},
        "source_version_id": {"type": "string", "pattern": SV_ID},
        "hearing_id": nullable("string"),
        "location": obj(
            ["page", "line_start", "line_end", "ordinal"],
            {
                "page": {"type": "integer", "minimum": 1},
                "line_start": {"type": "integer", "minimum": 1},
                "line_end": {"type": "integer", "minimum": 1},
                "ordinal": {"type": "integer", "minimum": 0},
            },
        ),
        "speaker": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["label", "entity_id", "role"],
            "properties": {"label": STR, "entity_id": nullable("string"), "role": nullable("string")},
        },
        "examination_phase": {"enum": PHASES},
        "unit_type": {"enum": ["speech_turn", "question", "answer", "decision", "caption", "other"]},
        "text": {"type": "string", "minLength": 1},
        "normalized_text": STR,
        "court_record_status": CRS_REF,
        # ADR-0010 additive: a speech turn split at a page break keeps a
        # shared turn key so readers can reassemble it; citations still
        # point at the per-page unit.
        "turn_key": nullable("string"),
        "turn_part": {"type": "integer", "minimum": 0},
        "synthetic_lines": {"type": "boolean"},
        "provenance": obj(
            ["content_sha256", "parser_version", "created_at"],
            {"content_sha256": {"type": "string", "pattern": SHA}, "parser_version": STR, "created_at": DT},
        ),
    },
)
defs["Review"] = obj(
    ["state", "risk_flags"],
    {
        "state": {"enum": REVIEW_STATES},
        "risk_flags": arr(STR, uniqueItems=True),
        "reviewer": nullable("string"),
        "reviewed_at": nullable("string", format="date-time"),
    },
)
defs["HearingDigest"] = obj(
    ["schema_version", "id", "hearing_id", "summary", "topics", "notable_exchanges", "citations", "review"],
    {
        "schema_version": {"const": SV},
        "id": STR,
        "hearing_id": STR,
        "summary": STR,
        "topics": arr(STR, uniqueItems=True),
        "persons": arr(STR, uniqueItems=True),
        "notable_exchanges": arr(
            obj(
                ["question_unit_id", "answer_unit_id", "answer_relation", "confidence"],
                {
                    "question_unit_id": STR,
                    "answer_unit_id": STR,
                    "answer_relation": {"enum": ANSWER_REL},
                    "interpreted_proposition": nullable("string"),
                    "confidence": CONF,
                },
            )
        ),
        "judicial_candidates": arr(STR),
        "citations": arr(ref("Citation"), minItems=1),
        "review": ref("Review"),
        # ADR-0010 additive: per-sentence citation mapping for the summary.
        "summary_sentences": arr(
            obj(["text", "citation_ids"], {"text": NESTR, "citation_ids": arr({"type": "string", "pattern": SU_ID}, minItems=1)})
        ),
    },
)
defs["EvidencePoint"] = obj(
    ["evidence_id", "summary", "direction", "court_record_status", "citation_ids"],
    {
        "evidence_id": UUID,
        "summary": STR,
        "direction": {"enum": DIRECTIONS},
        "court_record_status": CRS_REF,
        "citation_ids": arr(STR, minItems=1),
    },
)
defs["ClaimBundle"] = obj(
    ["schema_version", "claim_id", "claim_version_id", "question", "claim_text", "status", "as_of", "support",
     "weakness", "court_position", "citations", "review"],
    {
        "schema_version": {"const": SV},
        "claim_id": UUID,
        "claim_version_id": UUID,
        "question": STR,
        "claim_text": STR,
        "status": {"enum": CLAIM_STATUS},
        "as_of": DT,
        "support": arr(ref("EvidencePoint")),
        "weakness": arr(ref("EvidencePoint")),
        "court_position": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["level", "summary", "citation_ids"],
            "properties": {
                "level": {"enum": JUDICIAL_LEVELS},
                "summary": STR,
                "citation_ids": arr(STR, minItems=1),
            },
        },
        "unresolved_questions": arr(STR),
        "citations": arr(ref("Citation"), minItems=1),
        "review": ref("Review"),
        # ADR-0010 additive
        "answer_short": STR,
        "claim_type": STR,
        "disclosure": nullable("string"),
    },
)
defs["AnswerEnvelope"] = obj(
    ["schema_version", "answer_id", "permalink", "question", "answer_status", "as_of", "answer_short", "sections",
     "citations", "corpus_version", "review"],
    {
        "schema_version": {"const": SV},
        "answer_id": UUID,
        "permalink": {"type": "string", "format": "uri"},
        "question": STR,
        "normalized_question": STR,
        "answer_status": {
            "enum": ["answered", "insufficient_published_evidence", "false_premise_corrected", "requires_human_review", "refused"]
        },
        "as_of": DT,
        "answer_short": STR,
        "sections": arr(
            obj(
                ["kind", "text", "citation_ids"],
                {
                    "kind": {"enum": ["why", "supports", "weakens", "court_position", "status", "limitation"]},
                    "text": STR,
                    "citation_ids": arr(STR),
                },
            )
        ),
        "citations": arr(ref("Citation")),
        "corpus_version": STR,
        "warnings": arr(STR),
        "review": ref("Review"),
        # ADR-0010 additive: historical permalinks point to the current answer.
        "latest_permalink": nullable("string", format="uri"),
        "locale": STR,
    },
)

# --- additional objects required by the build brief -------------------------
defs["Document"] = obj(
    ["schema_version", "id", "case_id", "canonical_title", "source_type", "authority_tier", "source_owner"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": DOC_ID},
        "case_id": STR,
        "canonical_title": NESTR,
        "source_type": {"enum": SOURCE_TYPES},
        "authority_tier": {"type": "integer", "minimum": 1, "maximum": 5},
        "source_owner": NESTR,
        "source_stance": nullable("string"),
        "canonical_url": nullable("string", format="uri"),
        "language": STR,
        "legal_access_notes": nullable("string"),
    },
)
defs["SourceVersion"] = obj(
    ["schema_version", "id", "document_id", "content_sha256", "retrieved_at", "mime_type"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": SV_ID},
        "document_id": {"type": "string", "pattern": DOC_ID},
        "content_sha256": {"type": "string", "pattern": SHA},
        "retrieved_at": DT,
        "published_at": nullable("string", format="date-time"),
        "mime_type": NESTR,
        "size_bytes": nullable("integer", minimum=0),
        "object_uri": nullable("string"),
        "s3": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["bucket", "key"],
            "properties": {"bucket": NESTR, "key": NESTR, "version_id": nullable("string"), "etag": nullable("string")},
        },
        "source_url": nullable("string"),
        "parser_version": nullable("string"),
        "page_count": nullable("integer", minimum=1),
        "supersedes_id": nullable("string", pattern=SV_ID),
        "publication_state": {"enum": ["draft", "published", "withdrawn"]},
    },
)
defs["ExchangeUnit"] = obj(
    ["schema_version", "id", "hearing_id", "question_unit_id", "answer_unit_id", "phase", "answer_relation", "confidence", "review"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": QX_ID},
        "hearing_id": STR,
        "question_unit_id": {"type": "string", "pattern": SU_ID},
        "answer_unit_id": {"type": "string", "pattern": SU_ID},
        "asker_label": nullable("string"),
        "asker_side": nullable("string"),
        "witness_label": nullable("string"),
        "phase": {"enum": PHASES},
        "answer_relation": {"enum": ANSWER_REL},
        "interpreted_proposition": nullable("string"),
        "public_wording": nullable("string"),
        "confidence": CONF,
        "review": ref("Review"),
    },
)
defs["RetrievalChunk"] = obj(
    ["schema_version", "id", "source_version_id", "chunk_profile", "ordered_source_unit_ids", "token_count"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": RC_ID},
        "source_version_id": {"type": "string", "pattern": SV_ID},
        "chunk_profile": NESTR,
        "ordered_source_unit_ids": arr({"type": "string", "pattern": SU_ID}, minItems=1),
        "token_count": {"type": "integer", "minimum": 1, "maximum": 2000},
        "normalized_text": STR,
        "embedding_model": nullable("string"),
    },
)
defs["Hearing"] = obj(
    ["schema_version", "id", "case_id", "hearing_date"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": HR_ID},
        "case_id": STR,
        "hearing_date": DATE,
        "location": nullable("string"),
        "phase": nullable("string"),
        "witnesses": arr(STR),
        "judges": arr(STR),
        "source_document_ids": arr(STR),
        "source_version_id": nullable("string", pattern=SV_ID),
        "digest_id": nullable("string"),
        "topics": arr(STR),
    },
)
defs["Person"] = obj(
    ["schema_version", "id", "entity_type", "canonical_name", "aliases"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "entity_type": {"enum": ["person", "organization", "place", "other"]},
        "canonical_name": NESTR,
        "aliases": arr(STR, uniqueItems=True),
        "role_types": arr(STR),
        "role_periods": arr(
            obj(["role"], {"role": NESTR, "from": nullable("string", format="date"), "to": nullable("string", format="date")})
        ),
        "related_entities": arr(UUID),
    },
)
defs["Claim"] = obj(
    ["schema_version", "id", "case_id", "canonical_question", "claim_type", "title", "claim_text", "editorial_priority"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "version_id": nullable("string", format="uuid"),
        "case_id": STR,
        "slug": nullable("string"),
        "canonical_question": NESTR,
        "claim_type": {
            "enum": ["documented_fact", "prosecution_claim", "defense_claim", "testimony", "external_research",
                     "interpretation", "judicial_comment", "judicial_decision", "undecided"]
        },
        "title": NESTR,
        "claim_text": NESTR,
        "originator": nullable("string"),
        "stance": nullable("string"),
        "editorial_priority": {"type": "integer"},
        "confidence": nullable("number", minimum=0, maximum=1),
        "parent_claim_id": nullable("string", format="uuid"),
        "related_claim_ids": arr(UUID),
        "status": {"enum": CLAIM_STATUS},
        "valid_from": nullable("string", format="date-time"),
        "review": ref("Review"),
    },
)
defs["Evidence"] = obj(
    ["schema_version", "id", "case_id", "evidence_type", "summary", "court_record_status", "source_unit_ids"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "case_id": STR,
        "evidence_type": {"enum": ["testimony", "exchange", "document", "exhibit", "judicial_statement", "external", "other"]},
        "summary": NESTR,
        "event_date": nullable("string", format="date"),
        "person_entity_id": nullable("string", format="uuid"),
        "court_record_status": {"enum": CRS},
        "source_unit_ids": arr({"type": "string", "pattern": SU_ID}, minItems=1),
        "admissibility_note": nullable("string"),
        "contested": {"type": "boolean"},
        "contest_reason": nullable("string"),
        "review": ref("Review"),
    },
)
defs["Project315Event"] = obj(
    ["schema_version", "id", "external_event_id", "project315_page_url", "project315_classification",
     "court_record_status", "in_court_record", "independent_verification_status", "provenance"],
    {
        "schema_version": {"const": SV},
        "id": {"type": "string", "pattern": "^ev315_[0-9a-f]{26}$"},
        "external_event_id": NESTR,
        "indictment_reference": nullable("string"),
        "date_or_range": nullable(
            "object",
            additionalProperties=False,
            required=["from"],
            properties={"from": DATE, "to": nullable("string", format="date"), "raw": nullable("string")},
        ),
        "description": nullable("string"),
        "requester": nullable("string"),
        "recipient": nullable("string"),
        "subject": nullable("string"),
        "requested_action": nullable("string"),
        "prosecution_description": nullable("string"),
        "project315_classification": NESTR,
        "project315_reasoning_summary": nullable("string"),
        "netanyahu_involvement": nullable("string", enum=[*INVOLVEMENT, None]),
        "persons": arr(STR),
        "urls": arr(
            obj(
                ["url", "court_record_status"],
                {"url": {"type": "string", "format": "uri"}, "kind": nullable("string"), "court_record_status": {"enum": CRS}},
            )
        ),
        "court_mentions": arr(obj(["source_unit_id"], {"source_unit_id": {"type": "string", "pattern": SU_ID}, "note": nullable("string")})),
        "witness_mentions": arr(obj(["entity_id"], {"entity_id": UUID, "source_unit_id": nullable("string", pattern=SU_ID)})),
        "project315_page_url": {"type": "string", "format": "uri"},
        "court_record_status": {"enum": CRS},
        "in_court_record": {"type": "boolean"},
        "independent_verification_status": {"enum": VERIFICATION_315},
        "source_owner": {"const": "Project 315"},
        "source_stance": {"const": "defense-supportive"},
        "provenance": obj(
            ["raw_payload_sha256", "parser_version", "source", "imported_at"],
            {"raw_payload_sha256": {"type": "string", "pattern": SHA}, "parser_version": NESTR, "source": NESTR,
             "imported_at": DT, "synthetic": {"type": "boolean"}},
        ),
    },
)
defs["Artifact"] = obj(
    ["schema_version", "id", "artifact_type", "object_type", "object_id", "review"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "artifact_type": {"enum": ["summary", "claim_card", "answer", "seo_excerpt"]},
        "object_type": NESTR,
        "object_id": NESTR,
        "current_version_id": nullable("string", format="uuid"),
        "review": ref("Review"),
    },
)
defs["ArtifactVersion"] = obj(
    ["schema_version", "id", "artifact_id", "payload_schema", "payload", "model_run_id", "created_at"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "artifact_id": UUID,
        "payload_schema": {"enum": ["HearingDigest", "ClaimBundle", "AnswerEnvelope", "SeoExcerpt"]},
        "payload": {"type": "object"},
        "model_run_id": nullable("string", format="uuid"),
        "verifier_run_id": nullable("string", format="uuid"),
        "supersedes_id": nullable("string", format="uuid"),
        "created_at": DT,
    },
)
defs["ReviewTask"] = obj(
    ["schema_version", "id", "object_type", "object_id", "risk_flags", "status"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "object_type": NESTR,
        "object_id": NESTR,
        "risk_flags": arr(STR, uniqueItems=True),
        "reason": nullable("string"),
        "status": {"enum": ["open", "approved", "rejected", "changes_requested", "cancelled"]},
        "decision": nullable("string", enum=["approve", "reject", "revise", None]),
        "assigned_to": nullable("string"),
        "notes": nullable("string"),
        "writer_output": nullable("object"),
        "verifier_output": nullable("object"),
        "created_at": DT,
        "completed_at": nullable("string", format="date-time"),
    },
)
defs["Publication"] = obj(
    ["schema_version", "id", "artifact_id", "slug", "canonical_url", "knowledge_version", "published_at"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "artifact_id": UUID,
        "slug": NESTR,
        "canonical_url": {"type": "string", "format": "uri"},
        "knowledge_version": NESTR,
        "published_at": DT,
        "unpublished_at": nullable("string", format="date-time"),
    },
)
defs["IngestionJob"] = obj(
    ["schema_version", "id", "idempotency_key", "status", "stage", "stages"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "idempotency_key": NESTR,
        "status": {"enum": JOB_STATUS},
        "stage": NESTR,
        "source_version_id": nullable("string", pattern=SV_ID),
        "document_id": nullable("string", pattern=DOC_ID),
        "stages": arr(
            obj(
                ["stage", "status", "attempts"],
                {
                    "stage": {"enum": STAGES},
                    "status": {"enum": ["pending", "running", "succeeded", "failed", "skipped"]},
                    "attempts": {"type": "integer", "minimum": 0},
                    "started_at": nullable("string", format="date-time"),
                    "finished_at": nullable("string", format="date-time"),
                    "output": nullable("object"),
                    "error": nullable("object"),
                },
            )
        ),
        "error": nullable("object"),
        "created_at": DT,
        "updated_at": DT,
    },
)
defs["AuditEvent"] = obj(
    ["schema_version", "id", "occurred_at", "actor", "action", "object_type"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "occurred_at": DT,
        "actor": NESTR,
        "action": NESTR,
        "object_type": NESTR,
        "object_id": nullable("string"),
        "request_id": nullable("string"),
        "details": {"type": "object"},
    },
)
defs["ModelRun"] = obj(
    ["schema_version", "id", "role", "provider", "model_family", "model_version", "prompt_version", "schema_version_used",
     "temperature", "status", "input_hash", "input_source_ids", "created_at"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "role": {"enum": MODEL_ROLES},
        "provider": NESTR,
        "model_family": NESTR,
        "model_version": NESTR,
        "prompt_version": NESTR,
        "schema_version_used": NESTR,
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "status": {"enum": ["succeeded", "invalid_output", "provider_error", "rejected_by_gate"]},
        "input_hash": {"type": "string", "pattern": SHA},
        "output_hash": nullable("string", pattern=SHA),
        "input_source_ids": arr(STR),
        "usage": nullable("object"),
        "validation_errors": arr({"type": "object"}),
        "duration_ms": nullable("integer", minimum=0),
        "created_at": DT,
    },
)
defs["ModelRegistryEntry"] = obj(
    ["schema_version", "id", "role", "provider", "model_family", "model_id", "is_lite", "allowed_for_final", "active"],
    {
        "schema_version": {"const": SV},
        "id": NESTR,
        "role": {"enum": MODEL_ROLES},
        "provider": NESTR,
        "model_family": NESTR,
        "model_id": NESTR,
        "model_version": nullable("string"),
        "context_limit": nullable("integer", minimum=1),
        "price_snapshot": nullable("object"),
        "benchmark": nullable("object"),
        "is_lite": {"type": "boolean"},
        "allowed_for_final": {"type": "boolean"},
        "active": {"type": "boolean"},
    },
)
defs["CaseEvent"] = obj(
    ["schema_version", "id", "case_id", "event_type", "occurred_at", "title", "valid_from"],
    {
        "schema_version": {"const": SV},
        "id": UUID,
        "case_id": STR,
        "event_type": {
            "enum": ["indictment_decision", "indictment_filed", "hearing", "decision", "pardon_requested", "outcome",
                     "status_change", "political", "investigation", "publication", "other"]
        },
        "occurred_at": DT,
        "outcome": nullable("string", enum=[*OUTCOMES, None]),
        "title": NESTR,
        "description": nullable("string"),
        "source_unit_ids": arr({"type": "string", "pattern": SU_ID}),
        "external_sources": arr(obj(["url"], {"url": {"type": "string", "format": "uri"}, "label": nullable("string")})),
        "valid_from": DT,
        "valid_to": nullable("string", format="date-time"),
        "review": ref("Review"),
    },
)
defs["ErrorEnvelope"] = obj(
    ["code", "message", "request_id"],
    {
        "code": {
            "enum": ["invalid_request", "unsupported_schema", "unpublished_object", "insufficient_published_evidence",
                     "citation_gate_failed", "review_required", "rate_limited", "internal_error", "unauthorized",
                     "forbidden", "not_found", "conflict", "payload_too_large"]
        },
        "message": STR,
        "request_id": STR,
        "details": {"type": ["object", "array", "null"]},
    },
)

# --- model output contracts (validated before anything is stored) ------------
defs["ModelDigestOutput"] = obj(
    ["schema_version", "summary_sentences", "topics", "persons", "notable_exchange_ids", "judicial_candidate_unit_ids"],
    {
        "schema_version": {"const": SV},
        "summary_sentences": arr(
            obj(["text", "source_unit_ids"], {"text": NESTR, "source_unit_ids": arr({"type": "string", "pattern": SU_ID}, minItems=1)}),
            minItems=1,
        ),
        "topics": arr(NESTR),
        "persons": arr(NESTR),
        "exhibits": arr(STR),
        "dates": arr(STR),
        "claims_mentioned": arr(STR),
        "notable_exchange_ids": arr({"type": "string", "pattern": QX_ID}),
        "judicial_candidate_unit_ids": arr({"type": "string", "pattern": SU_ID}),
    },
)
defs["ModelMapperOutput"] = obj(
    ["schema_version", "claim_id", "evidence"],
    {
        "schema_version": {"const": SV},
        "claim_id": UUID,
        "evidence": arr(
            obj(
                ["source_unit_ids", "direction", "summary", "attribution"],
                {
                    "source_unit_ids": arr({"type": "string", "pattern": SU_ID}, minItems=1),
                    "direction": {"enum": DIRECTIONS},
                    "summary": NESTR,
                    "attribution": {
                        "enum": ["witness_said", "witness_affirmed_question", "counsel_asked", "prosecution_argued",
                                 "defense_argued", "judge_asked", "judge_commented", "court_decided", "document_states"]
                    },
                    "exchange_id": nullable("string", pattern=QX_ID),
                    "rationale": nullable("string"),
                },
            )
        ),
        "unresolved_questions": arr(STR),
        "decomposition": arr(NESTR),
    },
)
defs["ModelJudicialOutput"] = obj(
    ["schema_version", "classifications"],
    {
        "schema_version": {"const": SV},
        "classifications": arr(
            obj(
                ["source_unit_id", "is_judicial", "level", "confidence"],
                {
                    "source_unit_id": {"type": "string", "pattern": SU_ID},
                    "is_judicial": {"type": "boolean"},
                    "level": nullable("string", enum=[*JUDICIAL_LEVELS, None]),
                    "summary": nullable("string"),
                    "confidence": CONF,
                },
            )
        ),
    },
)
defs["ModelVerifierOutput"] = obj(
    ["schema_version", "assertions", "omitted_counterevidence", "verdict"],
    {
        "schema_version": {"const": SV},
        "assertions": arr(
            obj(
                ["path", "supported", "attribution_ok"],
                {
                    "path": NESTR,
                    "supported": {"enum": ["yes", "partial", "no"]},
                    "attribution_ok": {"type": "boolean"},
                    "judicial_overstatement": {"type": "boolean"},
                    "false_premise": {"type": "boolean"},
                    "note": nullable("string"),
                },
            )
        ),
        "omitted_counterevidence": arr(obj(["source_unit_ids"], {"source_unit_ids": arr(STR, minItems=1), "note": nullable("string")})),
        "verdict": {"enum": ["pass", "fail", "needs_human"]},
    },
)
defs["ModelAnswerDraft"] = obj(
    ["schema_version", "answer_status", "answer_short", "sections"],
    {
        "schema_version": {"const": SV},
        "answer_status": {"enum": ["answered", "insufficient_published_evidence", "false_premise_corrected", "refused"]},
        "answer_short": STR,
        "answer_short_citation_ids": arr({"type": "string", "pattern": SU_ID}),
        "sections": arr(
            obj(
                ["kind", "text", "citation_ids"],
                {
                    "kind": {"enum": ["why", "supports", "weakens", "court_position", "status", "limitation"]},
                    "text": STR,
                    "citation_ids": arr({"type": "string", "pattern": SU_ID}),
                },
            )
        ),
        "premise_issues": arr(STR),
    },
)
defs["ModelQARelationOutput"] = obj(
    ["schema_version", "items"],
    {
        "schema_version": {"const": SV},
        "items": arr(
            obj(
                ["exchange_id", "answer_relation", "confidence"],
                {
                    "exchange_id": {"type": "string", "pattern": QX_ID},
                    "answer_relation": {"enum": ANSWER_REL},
                    "interpreted_proposition": nullable("string"),
                    "confidence": CONF,
                },
            )
        ),
    },
)

DOC = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://knowledge.example.org/schemas/contracts-2.0.json",
    "title": "Netanyahu Trial Knowledge Contracts",
    "description": "Layer contracts: L0=SourceUnit, A=HearingDigest, B=ClaimBundle, C=AnswerEnvelope. Generated by tools/build_contracts.py",
    "$defs": defs,
}


def render() -> str:
    return json.dumps(DOC, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("contracts are stale: run python tools/build_contracts.py", file=sys.stderr)
            sys.exit(1)
        print("contracts up to date")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT} ({len(defs)} definitions)")
