# tests/unit/test_subprocess_utils.py
import os
import sys
import tracemalloc

import pytest

from app.orchestrator.subprocess_utils import (
    MAX_CAPTURED_BYTES,
    SubprocessResult,
    run_in_process_pool,
    run_subprocess,
)


class TestSubprocessResult:
    def test_create(self):
        result = SubprocessResult(returncode=0, stdout="hello", stderr="")
        assert result.returncode == 0
        assert result.stdout == "hello"

    def test_success_property(self):
        assert SubprocessResult(returncode=0, stdout="", stderr="").success is True
        assert SubprocessResult(returncode=1, stdout="", stderr="").success is False


class TestRunSubprocess:
    @pytest.mark.asyncio
    async def test_echo_command(self, tmp_path):
        result = await run_subprocess(
            command=["echo", "hello world"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_failing_command(self, tmp_path):
        result = await run_subprocess(
            command=["false"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode != 0

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        with pytest.raises(TimeoutError, match="timed out"):
            await run_subprocess(
                command=["sleep", "30"],
                cwd=tmp_path,
                timeout=1,
            )

    @pytest.mark.asyncio
    async def test_capture_stderr(self, tmp_path):
        result = await run_subprocess(
            command=[sys.executable, "-c", "import sys; sys.stderr.write('error msg')"],
            cwd=tmp_path,
            timeout=10,
        )
        assert "error msg" in result.stderr

    @pytest.mark.asyncio
    async def test_custom_env(self, tmp_path):
        result = await run_subprocess(
            command=[sys.executable, "-c", "import os; print(os.environ.get('TEST_VAR', ''))"],
            cwd=tmp_path,
            timeout=10,
            env={"TEST_VAR": "hello_from_env"},
        )
        assert "hello_from_env" in result.stdout


def _square(x: int) -> int:
    return x * x


class TestRunInProcessPool:
    @pytest.mark.asyncio
    async def test_single_function(self):
        result = await run_in_process_pool(_square, 5)
        assert result == 25

    @pytest.mark.asyncio
    async def test_max_workers_respected(self):
        result = await run_in_process_pool(_square, 7, max_workers=2)
        assert result == 49


class TestSubprocessOverflow:
    """CHAN-72: bounded capture with overflow spilled to tempfile."""

    @pytest.mark.asyncio
    async def test_small_output_not_truncated(self, tmp_path):
        result = await run_subprocess(
            command=[
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 1000)",
            ],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode == 0
        assert result.truncated is False
        assert result.stdout_capture.overflow_path is None
        assert result.stderr_capture.overflow_path is None
        assert len(result.stdout) == 1000
        assert result.overflow_logs() == []

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_large_stdout_streams_to_overflow_file(self, tmp_path):
        """Pipe 50MB of stdout and assert in-memory bound + overflow."""
        payload_size = 50_000_000

        tracemalloc.start()
        try:
            result = await run_subprocess(
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import sys;"
                        f"sys.stdout.buffer.write(b'x' * {payload_size})"
                    ),
                ],
                cwd=tmp_path,
                timeout=60,
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        try:
            # Bounded in-memory capture.
            assert result.returncode == 0
            assert result.truncated is True
            assert len(result.stdout_capture.data) <= MAX_CAPTURED_BYTES
            assert len(result.stdout) <= MAX_CAPTURED_BYTES

            # Overflow file exists and holds the full payload.
            overflow_path = result.stdout_capture.overflow_path
            assert overflow_path is not None
            assert os.path.exists(overflow_path)
            size_on_disk = os.path.getsize(overflow_path)
            # Within ~1% of 50MB.
            assert abs(size_on_disk - payload_size) < payload_size // 100

            # Stderr should be empty and not truncated.
            assert result.stderr_capture.truncated is False
            assert result.stderr_capture.overflow_path is None

            # overflow_logs() returns persistable metadata.
            logs = result.overflow_logs()
            assert len(logs) == 1
            assert logs[0]["stream"] == "stdout"
            assert logs[0]["path"] == overflow_path
            assert logs[0]["size_bytes"] == payload_size

            # Peak tracemalloc allocations for the capture path should
            # stay well under the full 50MB payload. 12 * MAX_CAPTURED_BYTES
            # leaves generous slack for bytearray resizing + the final
            # bytes() copy while still catching "we accidentally buffered
            # the whole 50MB" regressions.
            assert peak < MAX_CAPTURED_BYTES * 12, (
                f"tracemalloc peak {peak} exceeded bound; subprocess "
                "capture may be unbounded"
            )
        finally:
            if (
                result.stdout_capture.overflow_path
                and os.path.exists(result.stdout_capture.overflow_path)
            ):
                os.unlink(result.stdout_capture.overflow_path)


class TestSubprocessResultBackcompat:
    """String-constructor path used by older callers / existing tests."""

    def test_string_construction_still_works(self):
        result = SubprocessResult(returncode=0, stdout="hello", stderr="oops")
        assert result.stdout == "hello"
        assert result.stderr == "oops"
        assert result.truncated is False
        assert result.overflow_logs() == []
