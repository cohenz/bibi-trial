"""Curated questions and the wordings matched to them.

Revision ID: 0013
"""

from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0013_curated_questions.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0013 is not reversible in place")
