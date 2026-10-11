"""Model batches (Batch API).

Revision ID: 0011
"""

from pathlib import Path

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0011_model_batches.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0011 is not reversible in place")
