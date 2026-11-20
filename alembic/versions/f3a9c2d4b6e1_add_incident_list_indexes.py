"""add incident list indexes

Revision ID: f3a9c2d4b6e1
Revises: e7c1a4b92d10
Create Date: 2026-11-16

Round 1 (indexes). Targets the two statements that made up about 80% of
slow-query time in the Round 0 digest:

* officials' /incidents/assigned list:
    WHERE lower(district) = ... AND lower(tehsil) = ...
    ORDER BY created_at DESC, id DESC
* the unfiltered admin list:
    ORDER BY created_at DESC, id DESC

Indexes are built CONCURRENTLY so writes to incidents are not blocked, which
requires running outside a transaction (autocommit_block).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9c2d4b6e1"
down_revision: str | Sequence[str] | None = "e7c1a4b92d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_incidents_created_at_id",
            "incidents",
            [sa.text("created_at DESC"), sa.text("id DESC")],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_incidents_district_tehsil_created",
            "incidents",
            [
                sa.text("lower(district)"),
                sa.text("lower(tehsil)"),
                sa.text("created_at DESC"),
                sa.text("id DESC"),
            ],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_incidents_district_tehsil_created",
            table_name="incidents",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_incidents_created_at_id",
            table_name="incidents",
            postgresql_concurrently=True,
        )
