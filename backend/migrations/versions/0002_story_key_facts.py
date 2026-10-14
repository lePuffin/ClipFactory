"""Persist the extract_claims key-fact ranking on the selected Story."""

import sqlalchemy as sa
from alembic import op

revision = "0002_story_key_facts"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("story")}
    if "key_fact_claim_ids" in columns:
        return
    op.add_column(
        "story",
        sa.Column("key_fact_claim_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("story", "key_fact_claim_ids", server_default=None)


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("story")}
    if "key_fact_claim_ids" in columns:
        op.drop_column("story", "key_fact_claim_ids")
