# ADR-0002: Deterministic identifiers everywhere

**Status:** accepted

**Context.** Spec §27.4 defines `stable_id(prefix, parts)` for SourceVersion/SourceUnit/exchanges/chunks. The baseline SQL (§25) however uses `gen_random_uuid()` defaults for layer A/B/C rows, claims, entities, model runs and artifacts; random ids would make every re-run create duplicates, violating the brief's idempotency requirement ("rerun must not create new ids or duplicates").

**Decision.**
* `ids.stable_id` is byte-for-byte identical to `ntk.stable_id()` (pinned by a test vector in Python and SQL).
* SourceUnit ids are computed from `source_version_id, page, line_start, line_end, ordinal, normalized speaker label`; **text is not part of the key**, so normalisation fixes never break citations.
* Rows whose SQL type is `uuid` get **UUIDv5** ids derived from their inputs (namespace `NTK_NAMESPACE`), e.g. model run = (task, provider, model, prompt version, input hash); claim = (case, slug); artifact = (claim, version, citations hash, mapper run). The SQL defaults remain as a fallback only.
* Model calls are cached by run id: re-running a stage with identical inputs never calls the provider again.

**Verified by** `tests/integration/test_db_pipeline.py::test_rerun_is_idempotent` (table counts identical after a full re-run) and `test_changed_bytes_create_new_version_with_supersedes`.
