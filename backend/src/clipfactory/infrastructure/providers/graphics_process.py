"""Owned local render process with bounded logs, timeout and exact child cleanup."""

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GenerationProgress


async def run_graphics_process(
    arguments: list[str], *, cwd: Path, timeout_seconds: float, progress: GenerationProgress | None = None
) -> None:
    environment = {
        **os.environ,
        "HYPERFRAMES_TELEMETRY_DISABLED": "1",
        "DO_NOT_TRACK": "1",
        "HYPERFRAMES_NO_TELEMETRY": "1",
        "HF_HUB_OFFLINE": "1",
    }
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=cwd,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        raise ProviderError(
            "graphics_render_failed", "Local renderer executable is unavailable", transient=False
        ) from exc
    output = bytearray()

    async def read_output() -> None:
        assert process.stdout is not None
        while chunk := await process.stdout.read(4096):
            output.extend(chunk)
            if len(output) > 262144:
                del output[:-262144]

    async def heartbeat() -> None:
        while process.returncode is None:
            if progress is not None:
                await progress("", {"generation_phase": "heartbeat"})
            await asyncio.sleep(2)

    reader = asyncio.create_task(read_output())
    pulse = asyncio.create_task(heartbeat())
    try:
        async with asyncio.timeout(timeout_seconds):
            await process.wait()
            await reader
        if process.returncode:
            raise ProviderError(
                "graphics_render_failed", "Local renderer failed; inspect retained working files", transient=False
            )
    except TimeoutError as exc:
        raise ProviderError(
            "graphics_render_failed", "Local renderer exceeded its configured timeout", transient=False
        ) from exc
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if process.returncode is None:
            # All descendants belong to this session, never a global process-name kill.
            await process.wait()
        pulse.cancel()
        reader.cancel()
        await asyncio.gather(pulse, reader, return_exceptions=True)
        await asyncio.to_thread((cwd / "renderer.log").write_bytes, bytes(output))
