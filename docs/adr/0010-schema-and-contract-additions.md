# ADR-0010: Additive schema and contract changes

All changes are additive; the spec's tables and contract fields are unchanged.

**Schema (0002/0004):** source version storage fields (bucket, key, version id, ETag, size), publication state; SourceUnit `turn_key/turn_part`, speaker role/side, witness, search forms; exchange wording/flags; chunk search forms and filters; claim slug/thesis code/sensitivity; uploads; ingestion job stages (checkpoints); dead letters; model registry; model run metadata; answers; corpus versions; append-only audit; webhook outbox; Project 315 mentions, import runs and event versions; immutability triggers on source rows; public read views.

**Contracts:** optional fields `SourceUnit.turn_key/turn_part/synthetic_lines`, `HearingDigest.summary_sentences` (per-sentence citations), `ClaimBundle.answer_short/claim_type/disclosure`, `AnswerEnvelope.latest_permalink/locale`; new definitions for every object named in the brief and for each model output.
