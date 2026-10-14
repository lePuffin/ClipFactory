import asyncio
from pathlib import Path

import pytest

from clipfactory.infrastructure.media.runner import MediaProcessError, MediaRunner


@pytest.mark.unit
@pytest.mark.req("CF-REQ-353")
@pytest.mark.req("CF-NFR-102")
def test_media_runner_rejects_network_protocol_arguments() -> None:
    runner = MediaRunner("/usr/bin/true", "/usr/bin/true")

    async def attempt() -> None:
        await runner.ffmpeg(["-i", "https://example.com/video.mp4", "out.mp4"])

    with pytest.raises(ValueError, match="network protocols"):
        asyncio.run(attempt())


@pytest.mark.unit
@pytest.mark.req("CF-NFR-102")
@pytest.mark.asyncio
async def test_media_runner_invokes_argument_array_and_keeps_shell_metacharacters_literal(
    monkeypatch, tmp_path: Path
) -> None:
    runner = MediaRunner("/usr/bin/true", "/usr/bin/true")
    input_path = str(tmp_path / "a;touch marker.mp4")
    calls: list[tuple[object, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"ok", b""

    async def create_process(*args: object, **kwargs: object) -> Process:
        calls.append(args)
        assert kwargs["stdin"] is not None
        return Process()

    monkeypatch.setattr("asyncio.create_subprocess_exec", create_process)
    output, _ = await runner.ffmpeg(["-i", input_path, "out.mp4"])
    assert output == b"ok"
    assert calls[0][0] == runner.ffmpeg_path
    assert calls[0][1:4] == ("-protocol_whitelist", "file,pipe", "-i")
    assert calls[0][4] == input_path


@pytest.mark.unit
@pytest.mark.req("CF-NFR-012")
@pytest.mark.asyncio
async def test_media_runner_times_out_and_kills_process(monkeypatch) -> None:
    runner = MediaRunner("/usr/bin/true", "/usr/bin/true", timeout_seconds=0.01)

    class Process:
        returncode = -9
        killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            if self.killed:
                return b"", b""
            await asyncio.sleep(1)
            return b"", b""

        def kill(self) -> None:
            self.killed = True

    process = Process()

    async def create_process(*_args: object, **_kwargs: object) -> Process:
        return process

    import asyncio

    monkeypatch.setattr("asyncio.create_subprocess_exec", create_process)
    with pytest.raises(MediaProcessError, match="time limit"):
        await runner.ffmpeg(["-version"])
    assert process.killed
