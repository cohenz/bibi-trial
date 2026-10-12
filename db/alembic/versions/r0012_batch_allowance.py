"""Batch allowance (approved requests not yet sent).

Revision ID: 0012
"""

from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0012_batch_allowance.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0012 is not reversible in place")
