"""Object-store inbox: intake items, scans, extra source types.

Revision ID: 0006
"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "migrations" / "0006_inbox.sql"


def upgrade() -> None:
    op.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # enum values cannot be removed in place; the tables can
    op.execute("DROP TABLE IF EXISTS ntk.inbox_items; DROP TABLE IF EXISTS ntk.inbox_scans")
