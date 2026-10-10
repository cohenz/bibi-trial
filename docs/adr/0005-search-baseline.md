# ADR-0005: Hebrew search baseline in PostgreSQL; OpenSearch deferred

**Status:** accepted (per brief: no OpenSearch in V1)

**Decision.** `SearchBackend` interface; V1 implementation `PostgresSearchBackend` fuses six ranked signals with Reciprocal Rank Fusion: exact identifiers/quoted phrases, folded+prefix-stripped+alias terms (GIN on `text[]`), pg_trgm word similarity, character 3-grams on chunks, pgvector cosine on chunks (with a distance ceiling), and graph expansion (entities, published claim citations, Project 315 events). Filters (case, dates, witness, phase, court_record_status, publication) are applied inside every signal before ranking. Results are always SourceUnits; chunk hits are mapped back to their member units.

**Benchmark.** `trial-knowledge bench --suite golden/search-bench-*.json` reports Recall@20, nDCG@10, p50/p95 latency and `opensearch_recommended` when thresholds (default R@20 ≥ 0.85, nDCG@10 ≥ 0.6, p95 ≤ 800 ms) are missed. An OpenSearch adapter would implement `SearchBackend` only; API and contracts do not change.

**Relevance floor.** Ask uses only hits that carry a lexical/identifier/graph signal or agreement of two signals — fuzzy-only matches are not enough to answer from.
