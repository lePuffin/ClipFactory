"""Add canonical music metadata and durable workflow stage artifacts."""

import sqlalchemy as sa
from alembic import op

from clipfactory.infrastructure.db.models import JSON_DOCUMENT

revision = "0003_production_artifacts"
down_revision = "0002_story_key_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    asset_columns = {column["name"] for column in inspector.get_columns("asset")}
    if "music" not in asset_columns:
        op.add_column("asset", sa.Column("music", JSON_DOCUMENT, nullable=True))
    if "stage_artifact" not in inspector.get_table_names():
        op.create_table(
            "stage_artifact",
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("stage", sa.String(length=40), nullable=False),
            sa.Column("value", JSON_DOCUMENT, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["run.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("run_id", "attempt", "stage"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "stage_artifact" in inspector.get_table_names():
        op.drop_table("stage_artifact")
    asset_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("asset")}
    if "music" in asset_columns:
        op.drop_column("asset", "music")
