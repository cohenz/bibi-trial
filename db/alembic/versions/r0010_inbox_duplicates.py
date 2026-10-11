"""Intake duplicates: removed and possible_duplicate statuses, fingerprints.

Revision ID: 0010
"""

from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0010_inbox_duplicates.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0010 is not reversible in place")
