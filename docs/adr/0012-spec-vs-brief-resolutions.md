# ADR-0012: Conflicts between the brief and the spec — resolved toward the stricter rule

| Topic | Spec / brief | Decision |
|---|---|---|
| HNSW on vector(3072) | spec §25 | not possible in pgvector; `halfvec` or dim ≤ 2000 (ADR-0003) |
| `gen_random_uuid()` for derived rows | spec §25 vs idempotency in brief | deterministic UUIDv5 (ADR-0002) |
| Auto-publication after verification | spec §10 step 9 allows publishing verified items | nothing auto-publishes; explicit approve + publish (ADR-0008) |
| Single-family verifier | brief allows running the chain | allowed, but every sensitive/judicial/affirmation item → human review (ADR-0007) |
| `in_court_record` | brief lists it as a field | stored as a generated column derived from `court_record_status` (spec §23.7) |
| Q/A "affirmed" wording | spec §23.3 | produced only for clean `affirms`/`denies`, never when interrupted or asker unknown; published only after verification |
| OpenSearch | spec allows later | not a dependency (brief); interface only (ADR-0005) |
| Object storage | brief says S3 | Cloudflare R2 via S3 API (user decision; ADR-0011) |
