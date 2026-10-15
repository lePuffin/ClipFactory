from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
@pytest.mark.req("CF-REQ-652")
def test_queue_migration_preserves_orders_and_enforces_single_execution(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0009_serial_run_queue.py"
    spec = spec_from_file_location("serial_run_queue_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0008_profile_research"
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE run (id TEXT PRIMARY KEY, status TEXT, snapshot TEXT)")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_run_one_active ON run ((1)) WHERE status IN ('queued', 'running')"
            )
            connection.exec_driver_sql("INSERT INTO run VALUES ('first', 'running', 'original')")
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.exec_driver_sql("INSERT INTO run VALUES ('second', 'queued', 'frozen')")
            connection.exec_driver_sql("INSERT INTO run VALUES ('third', 'queued', 'frozen')")
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.exec_driver_sql("UPDATE run SET status = 'running' WHERE id = 'second'")
            assert list(connection.exec_driver_sql("SELECT id, status, snapshot FROM run ORDER BY id")) == [
                ("first", "running", "original"),
                ("second", "queued", "frozen"),
                ("third", "queued", "frozen"),
            ]
            connection.exec_driver_sql("UPDATE run SET status = 'completed' WHERE id = 'first'")
            connection.exec_driver_sql("UPDATE run SET status = 'running' WHERE id = 'second'")
            connection.exec_driver_sql("UPDATE run SET status = 'failed' WHERE id = 'third'")
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.exec_driver_sql("INSERT INTO run VALUES ('fourth', 'queued', 'frozen')")
    finally:
        engine.dispose()
