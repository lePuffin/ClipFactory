"""Allow deleting saved profiles while retaining immutable Run snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0006_profile_run_retention"
down_revision = "0005_render_revisions"
branch_labels = None
depends_on = None


def _profile_foreign_key() -> str:
    for constraint in sa.inspect(op.get_bind()).get_foreign_keys("run"):
        if constraint["constrained_columns"] == ["profile_id"]:
            return constraint["name"] or "fk_run_profile_id_content_profile"
    raise RuntimeError("Run profile foreign key was not found")


def upgrade() -> None:
    constraint = _profile_foreign_key()
    with op.batch_alter_table(
        "run", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    ) as batch:
        batch.drop_constraint(constraint, type_="foreignkey")
        batch.alter_column("profile_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_foreign_key("run_profile_id_fkey", "content_profile", ["profile_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # Restoring a required reference fails if a historical profile has been deleted.
    with op.batch_alter_table("run") as batch:
        batch.drop_constraint("run_profile_id_fkey", type_="foreignkey")
        batch.alter_column("profile_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("run_profile_id_fkey", "content_profile", ["profile_id"], ["id"])
