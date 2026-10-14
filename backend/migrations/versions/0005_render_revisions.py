"""Retain independently reviewed saved-package render revisions."""

import sqlalchemy as sa
from alembic import op

from clipfactory.infrastructure.db.models import JSON_DOCUMENT

revision = "0005_render_revisions"
down_revision = "0004_source_author_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "render_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("base_clip_id", sa.Uuid(), sa.ForeignKey("clip.id"), nullable=False),
        sa.Column("value", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_render_revision_base_clip_id", "render_revision", ["base_clip_id"])


def downgrade() -> None:
    op.drop_table("render_revision")
