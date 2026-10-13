"""Pydantic v2 request/response models for the Knowledge API.

Layer payloads (SourceUnit, HearingDigest, ClaimBundle, AnswerEnvelope) are
validated against the JSON Schema contracts in /contracts; these models
describe the HTTP envelopes around them."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SHA256 = r"^[0-9a-fA-F]{64}$"


class ErrorEnvelope(BaseModel):
    code: Literal[
        "invalid_request", "unsupported_schema", "unpublished_object", "insufficient_published_evidence",
        "citation_gate_failed", "review_required", "rate_limited", "internal_error", "unauthorized", "forbidden",
        "not_found", "conflict", "payload_too_large",
    ]
    message: str
    request_id: str
    details: Any = None


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"question": "מה אמרו השופטים על עבירת השוחד?", "as_of": "2026-10-10T00:00:00Z", "locale": "he",
         "client_request_id": "wp-3f9c2a"}]})
    question: str = Field(min_length=1, max_length=2000)
    as_of: dt.datetime | None = None
    locale: Literal["he", "en"] = "he"
    client_request_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


class SearchFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    witness: str | None = Field(default=None, max_length=100)
    phase: Literal["preliminary", "direct", "cross", "redirect", "recross", "court_questions", "argument", "unknown"] | None = None
    court_record_status: list[Literal["filed", "admitted", "marked_for_identification", "referenced_in_court", "excluded",
                                      "not_filed", "external", "unknown"]] | None = None
    hearing_id: str | None = Field(default=None, max_length=40)


class SearchRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"query": "פגישת ההנחיה", "filters": {"phase": "cross"}, "limit": 20}]})
    query: str = Field(min_length=1, max_length=300)
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)
    limit: int = Field(default=20, ge=1, le=50)


class PresignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"filename": "13.04.21.pdf", "mime_type": "application/pdf", "size_bytes": 1843200,
         "sha256": "0" * 64}]})
    filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["application/pdf"]
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=SHA256)

    @field_validator("filename")
    @classmethod
    def no_path(cls, v: str) -> str:
        if "/" in v or "\\" in v or v.startswith("."):
            raise ValueError("filename must not contain a path")
        return v


class PresignResponse(BaseModel):
    upload_id: str
    method: str
    url: str
    headers: dict[str, str]
    bucket: str
    key: str
    expires_in: int
    already_exists: bool


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    hearing_date: dt.date | None = None
    url: str | None = Field(default=None, max_length=1000)
    source_type: Literal["indictment", "protocol", "decision", "motion", "exhibit", "article", "recording", "regulatory",
                         "project315", "other"] = "protocol"
    authority_tier: int = Field(default=1, ge=1, le=5)
    source_owner: str = Field(default="הרשות השופטת", max_length=200)
    court_record_status: Literal["filed", "admitted", "marked_for_identification", "referenced_in_court", "excluded",
                                 "not_filed", "external", "unknown"] = "unknown"


class IngestionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"upload_id": "6c0b8a8e-4f4e-5b52-9a3e-1f0e2c7d9a10",
         "document": {"title": "פרוטוקול דיון 13.04.2021", "hearing_date": "2021-04-13", "court_record_status": "filed"},
         "claim_ids": []}]})
    upload_id: str | None = None
    s3_key: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, max_length=1000)
    document: DocumentIn
    claim_ids: list[str] = Field(default_factory=list, max_length=50)
    stages: list[str] | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "revise"]
    notes: str | None = Field(default=None, max_length=4000)


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_sources: bool = False


class UnpublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    question: str = Field(min_length=5, max_length=500)
    title: str = Field(min_length=3, max_length=300)
    claim_text: str = Field(min_length=5, max_length=4000)
    claim_type: Literal["documented_fact", "prosecution_claim", "defense_claim", "testimony", "external_research",
                        "interpretation", "judicial_comment", "judicial_decision", "undecided"]
    stance: str | None = Field(default=None, max_length=50)
    editorial_priority: int = 0
    thesis_code: str | None = Field(default=None, max_length=10)
    sensitivity: list[str] = Field(default_factory=list)
    disclosure: str | None = Field(default=None, max_length=1000)


class PriorityIn(BaseModel):
    editorial_priority: int


class CaseEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["indictment_decision", "indictment_filed", "hearing", "decision", "pardon_requested", "outcome",
                        "status_change", "political", "investigation", "publication", "other"]
    occurred_at: dt.datetime
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    outcome: Literal["verdict", "plea_deal", "withdrawal", "dismissal", "pardon_granted", "pardon_denied", "stay",
                     "mistrial", "other"] | None = None
    source_unit_ids: list[str] = Field(default_factory=list)
    external_sources: list[dict] = Field(default_factory=list)
    publish: bool = False


class ObjectReviewRequest(ReviewRequest):
    pass


class Project315ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["json", "csv"] = "json"
    source: str = Field(min_length=3, max_length=500, description="where the export came from (URL or file name)")
    content: str = Field(min_length=2, description="the raw export (JSON array/object or CSV text)")
    synthetic: bool = False


class StageRerunRequest(BaseModel):
    """Re-run named stages of an existing job (e.g. after a model change). Other stages keep their results."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"stages": ["embed", "extract_a", "verify"]}]})
    stages: list[str] = Field(min_length=1, max_length=15)
    # a job left 'running' by a worker that was stopped mid-task (its message only comes back after the broker's
    # visibility timeout) may be re-run once it has not progressed for STALE_JOB_MINUTES
    force_stale: bool = False


class EvaluationRequest(BaseModel):
    """Run a golden suite on the worker against the deployed corpus and models."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"kind": "search_bench", "suite": "search-bench-real-sept2025-v1", "published_only": False},
        {"kind": "ask_suite", "suite": "real-sept2025-v1"}]})
    kind: Literal["search_bench", "ask_suite"]
    suite: str = Field(min_length=1, max_length=120)
    published_only: bool = False
    as_of: dt.datetime | None = None


class GuideBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["indictment", "cases", "witnesses", "all"] = "all"
    source_version_id: str | None = Field(default=None, pattern=r"^sv_[0-9a-f]{26}$")
    keys: list[str] | None = Field(default=None, max_length=50)


class DigestBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hearing_ids: list[str] | None = Field(default=None, max_length=500)
    limit: int = Field(default=20, ge=1, le=500)


class DigestBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hearing_ids: list[str] | None = Field(default=None, max_length=1000)
    # approved number of requests: what the provider takes now is sent, the rest as earlier batches finish; 0 cancels
    limit: int = Field(default=200, ge=0, le=1000)
    now: bool = False  # run in this request instead of the worker queue (the queue may be busy for hours)


class BatchSubmitRequest(BaseModel):
    """Any batch kind (13.10.2026): digest | witness_guide | document_brief."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["digest", "witness_guide", "document_brief"]
    keys: list[Annotated[str, StringConstraints(pattern=r"^(hr_[0-9a-f]{26}|w_[0-9a-f]{10}|sv_[0-9a-f]{26})$")]] | None = Field(
        default=None, max_length=1000)
    limit: int = Field(default=200, ge=0, le=1000)  # an approval; 0 cancels what is left of the previous one
    now: bool = False


class BriefBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_version_ids: list[str] | None = Field(default=None, max_length=2000)
    only_missing: bool = True


class NonHearingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apply: bool = False  # false: list what would change
    # an operator's call on records the rule misses (e.g. a motion that mentions "נוכחים"): these hearings, as this type
    hearing_ids: list[Annotated[str, StringConstraints(pattern=r"^hr_[0-9a-f]{26}$")]] | None = Field(None, max_length=50)
    kind: Literal["decision", "notice", "motion", "response", "other"] | None = None


class DuplicateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # remove_copy: delete this intake copy, keep the document already in the system
    # keep_and_process: it is a different document; store and ingest it
    action: Literal["remove_copy", "keep_and_process"]


class InboxScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None: follow NTK_INBOX_AUTO_PROCESS; False: classify only (a map of the documents); True: classify and ingest
    process: bool | None = False


class InboxProcessRequest(BaseModel):
    """Turn classified inbox items into ingestion jobs."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"kinds": ["protocol", "decision"]}]})
    kinds: list[Literal["protocol", "decision", "motion", "response", "notice", "affidavit", "indictment", "exhibit",
                        "other"]] | None = None
    item_ids: list[str] | None = Field(default=None, max_length=5000)
    limit: int = Field(default=5000, ge=1, le=20000)


class InboxItemOverride(BaseModel):
    """A reviewer's correction of an item's classification, or a decision to skip it."""
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["protocol", "decision", "motion", "response", "notice", "affidavit", "indictment", "exhibit",
                         "other"] | None = None
    hearing_date: dt.date | None = None
    document_date: dt.date | None = None
    title: str | None = Field(default=None, max_length=300)
    skip: bool = False
    case_number_verified: bool | None = None
