"""Async subprocess execution with timeout and process pool utilities."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class SubprocessResult:
    """Result of an async subprocess execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


async def run_subprocess(
    command: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run an external command asynchronously with timeout and capture output.

    Args:
        command: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Maximum execution time in seconds.
        env: Optional environment variable overrides (merged with os.environ).

    Returns:
        SubprocessResult with returncode, stdout, stderr.

    Raises:
        FileNotFoundError: If the executable is not found on PATH.
        TimeoutError: If the command exceeds the timeout.
    """
    merged_env = {**os.environ, **(env or {})}

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
    except FileNotFoundError as err:
        # Binary missing from PATH -- re-raise with a clear, structured message
        # so callers can catch FileNotFoundError specifically and degrade gracefully.
        binary = command[0] if command else "<unknown>"
        raise FileNotFoundError(f"Executable not found on PATH: {binary!r}") from err

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return SubprocessResult(
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError as err:
        proc.kill()
        await proc.wait()
        raise TimeoutError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        ) from err


async def run_in_process_pool(
    func: Callable[..., T],
    *args: Any,
    max_workers: int | None = None,
) -> T:
    """Run a CPU-bound function in a process pool.

    Args:
        func: Picklable function to execute.
        *args: Positional arguments for the function.
        max_workers: Max pool workers (default: os.cpu_count()).

    Returns:
        The function's return value.
    """
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=max_workers or os.cpu_count()) as pool:
        result = await loop.run_in_executor(pool, func, *args)
    return result
