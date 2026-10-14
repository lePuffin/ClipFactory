"""Materialize profile-owned research without changing historical Runs.

Revision ID: 0008_profile_research
Revises: 0007_multiple_active_profiles
"""

import sqlalchemy as sa
from alembic import op

from clipfactory.infrastructure.research_defaults import materialize_research

revision = "0008_profile_research"
down_revision = "0007_multiple_active_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    profiles = sa.table("content_profile", sa.column("id", sa.Uuid()), sa.column("value", sa.JSON()))
    settings = sa.table("app_settings", sa.column("section", sa.String()), sa.column("value", sa.JSON()))
    legacy = bind.scalar(sa.select(settings.c.value).where(settings.c.section == "research")) or {}
    for row in bind.execute(sa.select(profiles.c.id, profiles.c.value)).all():
        bind.execute(
            profiles.update().where(profiles.c.id == row.id).values(value=materialize_research(row.value, legacy))
        )


def downgrade() -> None:
    # Data is intentionally retained: dropping it would discard explicit profile policy.
    pass
