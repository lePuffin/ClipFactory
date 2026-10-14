import pytest
from sqlalchemy.engine import make_url

from clipfactory.infrastructure.db.checkpointer import open_postgres_checkpointer


class FakeCheckpointer:
    def __init__(self) -> None:
        self.setup_called = False

    async def setup(self) -> None:
        self.setup_called = True


class FakeCheckpointerContext:
    def __init__(self, checkpointer: FakeCheckpointer) -> None:
        self.checkpointer = checkpointer

    async def __aenter__(self) -> FakeCheckpointer:
        return self.checkpointer

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.req("CF-REQ-657")
async def test_checkpointer_converts_sqlalchemy_url_for_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    checkpointer = FakeCheckpointer()

    def from_conn_string(connection_url: str) -> FakeCheckpointerContext:
        captured.append(connection_url)
        return FakeCheckpointerContext(checkpointer)

    monkeypatch.setattr(
        "clipfactory.infrastructure.db.checkpointer.AsyncPostgresSaver.from_conn_string",
        from_conn_string,
    )

    async with open_postgres_checkpointer(
        "postgresql+psycopg://clipfactory:p%40ss@localhost:5432/clipfactory"
    ) as opened:
        assert opened is checkpointer

    assert checkpointer.setup_called is True
    normalized = make_url(captured[0])
    assert normalized.drivername == "postgresql"
    assert normalized.password == "p@ss"  # noqa: S105
