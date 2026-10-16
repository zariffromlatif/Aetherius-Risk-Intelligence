"""operator client assignments

Revision ID: 0002_operator_client_assignments
Revises: 0001_initial
Create Date: 2026-10-16
"""

from alembic import op

revision = "0002_operator_client_assignments"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(open("migrations/002_operator_client_assignments.sql", "r", encoding="utf-8").read())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operator_client_assignments")
