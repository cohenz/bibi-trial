# ADR-0003: Embedding dimension and `halfvec`

**Status:** accepted

**Context.** Spec §25 declares `embedding vector(3072)` with an HNSW index. pgvector's HNSW index supports at most **2,000 dimensions for `vector`** (4,000 for `halfvec`, available from pgvector 0.7). As written, the migration would fail.

**Decision.** The embedding column and index are created by Alembic revision `0003`, parameterised by `NTK_EMBEDDING_DIM` (default 3072):
* `dim ≤ 2000` → `vector(dim)` + `vector_cosine_ops`
* `2000 < dim ≤ 4000` → `halfvec(dim)` + `halfvec_cosine_ops` (migration refuses to run on pgvector < 0.7 with a clear message)

Changing the dimension later is an explicit migration (spec: "not a silent write into the same column").

**Notes.** Railway's pgvector Postgres template ships a recent pgvector; check `SELECT extversion FROM pg_extension WHERE extname='vector'` ≥ 0.7 before migrating with 3072. Local tests use 768 on pgvector 0.6.
