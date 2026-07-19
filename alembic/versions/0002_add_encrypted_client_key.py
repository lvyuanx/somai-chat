"""Store encrypted robot client Keys for administrator reveal.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_access_keys", sa.Column("encrypted_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("client_access_keys", "encrypted_key")
