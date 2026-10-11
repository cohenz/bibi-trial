"""Reader guides: artifact type "guide" (ADR-0015).

Revision ID: 0009
"""

from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0009_guides.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0009 is not reversible in place")
