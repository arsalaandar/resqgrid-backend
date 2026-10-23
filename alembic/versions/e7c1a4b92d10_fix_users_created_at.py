"""make users.created_at timezone-aware with a server default

Revision ID: e7c1a4b92d10
Revises: ca996a6546e7
Create Date: 2026-10-23 12:00:00.000000

Existing rows keep their (incorrect) stored value. Before this migration the
model default was evaluated once at import time, so rows created during one
application run share a single timestamp. Those historic values cannot be
reconstructed; they are interpreted as UTC when converted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a4b92d10"
down_revision: str | Sequence[str] | None = "ca996a6546e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.func.now(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        server_default=None,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
