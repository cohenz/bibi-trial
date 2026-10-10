"""Embedding column + HNSW index, parameterised by deployment (ADR-0003).

NTK_EMBEDDING_DIM (default 3072, the pilot default in spec §25):
* dim <= 2000  → vector(dim), hnsw (vector_cosine_ops)
* dim <= 4000  → halfvec(dim), hnsw (halfvec_cosine_ops); requires pgvector >= 0.7
Changing the dimension later is an explicit new migration, never a silent
write into the same column (spec §25).

Revision ID: 0003
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _pgvector_version(conn) -> tuple[int, ...]:
    v = conn.execute(sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
    return tuple(int(x) for x in (v or "0").split("."))


def upgrade() -> None:
    dim = int(os.environ.get("NTK_EMBEDDING_DIM", "3072"))
    if dim < 1 or dim > 4000:
        raise RuntimeError(f"NTK_EMBEDDING_DIM={dim} unsupported (1..4000)")
    conn = op.get_bind()
    if dim <= 2000:
        col, ops = f"vector({dim})", "vector_cosine_ops"
    else:
        if _pgvector_version(conn) < (0, 7):
            raise RuntimeError(
                f"NTK_EMBEDDING_DIM={dim} needs halfvec (pgvector >= 0.7) for an HNSW index; "
                "upgrade pgvector or choose a dimension <= 2000"
            )
        col, ops = f"halfvec({dim})", "halfvec_cosine_ops"
    op.execute(f"ALTER TABLE ntk.retrieval_chunks ADD COLUMN embedding {col}")
    op.execute(f"ALTER TABLE ntk.retrieval_chunks ADD COLUMN embedding_dim integer NOT NULL DEFAULT {dim}")
    op.execute(f"CREATE INDEX retrieval_chunks_embedding_idx ON ntk.retrieval_chunks USING hnsw (embedding {ops})")
    op.execute(
        "COMMENT ON COLUMN ntk.retrieval_chunks.embedding IS "
        f"'{col}; set by NTK_EMBEDDING_DIM at migration time (ADR-0003)'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ntk.retrieval_chunks_embedding_idx")
    op.execute("ALTER TABLE ntk.retrieval_chunks DROP COLUMN IF EXISTS embedding_dim")
    op.execute("ALTER TABLE ntk.retrieval_chunks DROP COLUMN IF EXISTS embedding")
