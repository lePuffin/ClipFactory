from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.integration
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-555")
def test_profile_retention_migration_preserves_run_snapshot(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0006_profile_deletion_preserves_runs.py"
    spec = spec_from_file_location("profile_retention_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    metadata = sa.MetaData()
    profiles = sa.Table("content_profile", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    runs = sa.Table(
        "run",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("content_profile.id"), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False),
    )
    profile_id, run_id = uuid4(), uuid4()
    snapshot = {"id": str(profile_id), "name": "Historic", "language": "es"}
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(profiles.insert().values(id=profile_id))
            connection.execute(runs.insert().values(id=run_id, profile_id=profile_id, profile_snapshot=snapshot))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            columns = {column["name"]: column for column in sa.inspect(connection).get_columns("run")}
            assert columns["profile_id"]["nullable"] is True
            assert sa.inspect(connection).get_foreign_keys("run")[0].get("options", {}).get("ondelete") == "SET NULL"
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            columns = {column["name"]: column for column in sa.inspect(connection).get_columns("run")}
            assert columns["profile_id"]["nullable"] is False
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.execute(profiles.delete().where(profiles.c.id == profile_id))
            connection.commit()
            saved = connection.execute(sa.select(runs)).one()
            assert saved.profile_id is None
            assert saved.profile_snapshot == snapshot
    finally:
        engine.dispose()
