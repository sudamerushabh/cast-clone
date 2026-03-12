# tests/unit/test_subprocess_utils.py
import asyncio
import sys

import pytest

from app.orchestrator.subprocess_utils import (
    SubprocessResult,
    run_subprocess,
    run_in_process_pool,
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
