"""Create the v1 domain and workflow schema."""

from alembic import op

from clipfactory.infrastructure.db import models as _models  # noqa: F401
from clipfactory.infrastructure.db.base import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
