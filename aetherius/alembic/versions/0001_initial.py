"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-31
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep pilot setup simple by reusing curated SQL migration.
    op.execute(open("migrations/001_initial_schema.sql", "r", encoding="utf-8").read())


def downgrade() -> None:
    pass
