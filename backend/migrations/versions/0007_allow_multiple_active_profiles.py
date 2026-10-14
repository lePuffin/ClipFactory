"""Allow multiple active content profiles with individual schedules.

Revision ID: 0007_multiple_active_profiles
Revises: 0006_profile_run_retention
Create Date: 2026-10-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0007_multiple_active_profiles"
down_revision = "0006_profile_run_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    indexes = {idx["name"] for idx in insp.get_indexes("content_profile")}
    if "uq_content_profile_active" in indexes:
        op.drop_index("uq_content_profile_active", table_name="content_profile")
    op.create_index("ix_content_profile_is_active", "content_profile", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_content_profile_is_active", table_name="content_profile")
    op.create_index(
        "uq_content_profile_active",
        "content_profile",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active"),
    )
