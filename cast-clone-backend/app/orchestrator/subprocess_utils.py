"""Async subprocess execution with timeout and process pool utilities."""

from __future__ import annotations

import asyncio
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# CHAN-72: bound the in-memory capture of subprocess stdout/stderr. Large
# Maven/Gradle logs (or runaway SCIP indexers) can produce hundreds of MB
# of output — if we let `proc.communicate()` buffer all of that into
# Python bytes, a single analysis can OOM the backend. 10MB is a generous
# ceiling for "enough to read and log" while the remainder streams to
# disk.
MAX_CAPTURED_BYTES = 10_000_000

# Chunk size for streaming from the child's pipes. 64KB matches the
# default asyncio StreamReader buffer high-water mark, so we don't stall
# the producer.
_CHUNK_SIZE = 64 * 1024

# CHAN-73: grace window between SIGTERM and SIGKILL when the pipeline
# cancels a running subprocess. 5s matches the acceptance criterion for
# the outer pipeline (pipeline exits within 5s of flag flip) and is
# plenty for a SCIP indexer / Maven build to flush its output and exit
# cleanly; if it hasn't, we escalate to SIGKILL.
_SIGTERM_GRACE_SECONDS = 5.0


class SubprocessCancelled(Exception):  # noqa: N818 - name fixed by CHAN-73 spec
    """Raised when ``run_subprocess`` is cancelled mid-run.

    CHAN-73: the caller (``asyncio.CancelledError`` propagated through
    the pipeline's cancellation check) interrupts a live child process;
    we send SIGTERM, wait up to ``_SIGTERM_GRACE_SECONDS``, then SIGKILL
    if it hasn't exited. Any stdout/stderr that had already spilled to
    overflow temp files is surfaced on ``overflow_logs`` so the pipeline
    can persist those paths to ``AnalysisRun.subprocess_logs`` — the
    partial log is still useful for post-mortem even though the run was
    interrupted.
    """

    def __init__(
        self,
        command: list[str],
        overflow_logs: list[dict[str, Any]] | None = None,
        killed: bool = False,
    ) -> None:
        self.command = command
        self.overflow_logs: list[dict[str, Any]] = overflow_logs or []
        self.killed = killed
        super().__init__(
            f"Subprocess cancelled: {' '.join(command)}"
            + (" (SIGKILL)" if killed else " (SIGTERM)")
        )


@dataclass
class StreamCapture:
    """Result of capturing a single stream (stdout or stderr).

    ``data`` holds up to ``MAX_CAPTURED_BYTES`` of the stream's contents.
    If the stream exceeded that cap, ``truncated`` is True and the full
    contents were spooled to ``overflow_path`` on disk. ``total_bytes``
    is the total number of bytes the child produced on this stream,
    regardless of truncation.
    """

    data: bytes
    truncated: bool
    overflow_path: str | None
    total_bytes: int


def _capture_from_value(value: str | bytes | None) -> StreamCapture:
    """Build a ``StreamCapture`` from a plain string/bytes payload.

    Used for the backwards-compat ``SubprocessResult(returncode=..,
    stdout="..", stderr="..")`` constructor call path.
    """
    if value is None:
        data = b""
    elif isinstance(value, str):
        data = value.encode("utf-8", errors="replace")
    else:
        data = bytes(value)
    return StreamCapture(
        data=data, truncated=False, overflow_path=None, total_bytes=len(data)
    )


class SubprocessResult:
    """Result of an async subprocess execution.

    The ``stdout`` / ``stderr`` properties return decoded strings of the
    captured (in-memory) portion, which is bounded by
    ``MAX_CAPTURED_BYTES``. Callers that need the full log (for audit or
    debugging) should read from the overflow file paths exposed on
    ``stdout_capture`` / ``stderr_capture`` (or via
    ``overflow_logs()`` as ready-to-persist dicts).
    """

    def __init__(
        self,
        returncode: int,
        stdout: str | bytes | None = None,
        stderr: str | bytes | None = None,
        stdout_capture: StreamCapture | None = None,
        stderr_capture: StreamCapture | None = None,
    ) -> None:
        self.returncode = returncode
        if stdout_capture is None:
            stdout_capture = _capture_from_value(stdout)
        if stderr_capture is None:
            stderr_capture = _capture_from_value(stderr)
        self.stdout_capture: StreamCapture = stdout_capture
        self.stderr_capture: StreamCapture = stderr_capture

    @property
    def stdout(self) -> str:
        return self.stdout_capture.data.decode("utf-8", errors="replace")

    @property
    def stderr(self) -> str:
        return self.stderr_capture.data.decode("utf-8", errors="replace")

    @property
    def truncated(self) -> bool:
        """True if either stream was truncated / spilled to disk."""
        return self.stdout_capture.truncated or self.stderr_capture.truncated

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def overflow_logs(self) -> list[dict[str, Any]]:
        """Return metadata for any overflow files produced.

        Suitable for persisting into ``AnalysisRun.subprocess_logs``:
        ``[{"stream": "stdout", "path": ..., "size_bytes": ...}, ...]``.
        """
        entries: list[dict[str, Any]] = []
        for name, cap in (
            ("stdout", self.stdout_capture),
            ("stderr", self.stderr_capture),
        ):
            if cap.truncated and cap.overflow_path is not None:
                entries.append(
                    {
                        "stream": name,
                        "path": cap.overflow_path,
                        "size_bytes": cap.total_bytes,
                    }
                )
        return entries


async def _drain_stream(
    reader: asyncio.StreamReader | None,
    stream_name: str,
    partial_sink: list[dict[str, Any]] | None = None,
) -> StreamCapture:
    """Read a child-process stream with a bounded in-memory buffer.

    Up to ``MAX_CAPTURED_BYTES`` are kept in memory. Anything beyond
    that is written to a ``NamedTemporaryFile`` (``delete=False``) so
    the caller can inspect it post-run. The temp file is closed here;
    cleanup is the caller's responsibility.

    CHAN-73: if ``partial_sink`` is provided, the overflow path is
    appended to it (as a ready-to-persist dict) as soon as the file is
    opened. This lets the caller observe the overflow even if the drain
    coroutine is later cancelled (e.g. the pipeline flipped
    ``context.cancelled``) and never reaches its ``return`` statement.
    """
    if reader is None:
        return StreamCapture(
            data=b"", truncated=False, overflow_path=None, total_bytes=0
        )

    buf = bytearray()
    total = 0
    overflow_file: Any = None
    overflow_path: str | None = None
    truncated = False
    recorded_partial = False

    try:
        while True:
            chunk = await reader.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)

            remaining = MAX_CAPTURED_BYTES - len(buf)
            if remaining > 0:
                take = min(remaining, len(chunk))
                buf.extend(chunk[:take])
                spillover = chunk[take:]
            else:
                spillover = chunk

            if spillover:
                if overflow_file is None:
                    overflow_file = tempfile.NamedTemporaryFile(
                        prefix=f"castclone-{stream_name}-",
                        suffix=".log",
                        delete=False,
                    )
                    overflow_path = overflow_file.name
                    truncated = True
                    # Flush what's already in memory so the overflow
                    # file contains the *full* stream, not just the
                    # tail past the cap. This keeps the on-disk file
                    # self-contained and useful for post-mortem.
                    overflow_file.write(bytes(buf))
                    if partial_sink is not None and not recorded_partial:
                        partial_sink.append(
                            {
                                "stream": stream_name,
                                "path": overflow_path,
                                # ``size_bytes`` is updated on-disk as we
                                # keep writing; the recorded dict carries
                                # the final value at whatever moment the
                                # caller reads it post-cancellation.
                                "size_bytes": total,
                            }
                        )
                        recorded_partial = True
                overflow_file.write(spillover)
    finally:
        if overflow_file is not None:
            overflow_file.flush()
            overflow_file.close()

    return StreamCapture(
        data=bytes(buf),
        truncated=truncated,
        overflow_path=overflow_path,
        total_bytes=total,
    )


async def run_subprocess(
    command: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run an external command asynchronously with timeout and capture output.

    Stdout/stderr are captured with a per-stream ``MAX_CAPTURED_BYTES``
    cap. Anything beyond that cap is spilled to per-stream temp files
    (``tempfile.NamedTemporaryFile(delete=False)``); the caller is
    responsible for cleaning those up (or archiving their paths via
    ``SubprocessResult.overflow_logs()``).

    Args:
        command: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Maximum execution time in seconds.
        env: Optional environment variable overrides (merged with os.environ).

    Returns:
        SubprocessResult with returncode and bounded stdout/stderr captures.

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

    # CHAN-73: partial_overflow is populated by the drain coroutines as
    # soon as they open an overflow tempfile. Even if the outer
    # coroutine is cancelled, this list survives so we can surface the
    # partial log locations through ``SubprocessCancelled``.
    partial_overflow: list[dict[str, Any]] = []

    async def _run() -> SubprocessResult:
        stdout_cap, stderr_cap = await asyncio.gather(
            _drain_stream(proc.stdout, "stdout", partial_overflow),
            _drain_stream(proc.stderr, "stderr", partial_overflow),
        )
        await proc.wait()
        return SubprocessResult(
            returncode=proc.returncode or 0,
            stdout_capture=stdout_cap,
            stderr_capture=stderr_cap,
        )

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError as err:
        proc.kill()
        await proc.wait()
        raise TimeoutError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        ) from err
    except asyncio.CancelledError:
        # CHAN-73: cooperative cancellation from the pipeline. SIGTERM
        # first, wait up to _SIGTERM_GRACE_SECONDS for the child to
        # clean up, then escalate to SIGKILL. Re-raise as
        # ``SubprocessCancelled`` carrying any partial overflow paths
        # so the pipeline can still persist them.
        killed = False
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                # Already exited between the CancelledError and our
                # terminate() — fine, nothing to kill.
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                else:
                    killed = True
                    try:
                        await proc.wait()
                    except asyncio.CancelledError:
                        # Second cancellation while reaping the kill —
                        # defer to normal CancelledError propagation
                        # after we finish raising below.
                        pass
        raise SubprocessCancelled(
            command=command,
            overflow_logs=list(partial_overflow),
            killed=killed,
        ) from None


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
