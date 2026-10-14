"""Preserve long article author metadata without truncation."""

import sqlalchemy as sa
from alembic import op

revision = "0004_source_author_text"
down_revision = "0003_production_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source") as batch:
        batch.alter_column("author", existing_type=sa.String(255), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("source") as batch:
        batch.alter_column("author", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=True)
