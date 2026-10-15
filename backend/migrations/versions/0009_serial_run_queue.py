"""Permit durable queued Runs alongside one executing Run."""

from alembic import op

revision = "0009_serial_run_queue"
down_revision = "0008_profile_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_run_one_active", table_name="run")
    op.execute("CREATE UNIQUE INDEX uq_run_one_active ON run ((1)) WHERE status = 'running'")


def downgrade() -> None:
    # Refuse to discard pending orders: the previous constraint may reject downgrade.
    op.drop_index("uq_run_one_active", table_name="run")
    op.execute("CREATE UNIQUE INDEX uq_run_one_active ON run ((1)) WHERE status IN ('queued', 'running')")
