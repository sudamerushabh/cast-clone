"""Git clone, checkout, and pull operations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import structlog

logger = structlog.get_logger()


def build_authenticated_url(clone_url: str, token: str) -> str:
    parsed = urlparse(clone_url)
    authed = parsed._replace(
        netloc=f"{token}@{parsed.hostname}"
        + (f":{parsed.port}" if parsed.port else "")
    )
    return urlunparse(authed)


def strip_token_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "@" in (parsed.netloc or ""):
        host_part = parsed.netloc.split("@", 1)[1]
        cleaned = parsed._replace(netloc=host_part)
        return urlunparse(cleaned)
    return url


async def clone_repo(
    clone_url: str, token: str, target_dir: str, timeout: int = 600
) -> None:
    auth_url = build_authenticated_url(clone_url, token)
    target = Path(target_dir)
    resolved = target.resolve()
    if not str(resolved).startswith(str(target.parent.resolve())):
        raise ValueError(f"Invalid clone target: {target_dir}")
    target.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git",
        "clone",
        auth_url,
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"Clone timed out after {timeout}s")

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        error_msg = error_msg.replace(token, "***")
        raise RuntimeError(f"Clone failed: {error_msg}")

    # Strip token from remote URL
    proc2 = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(target),
        "remote",
        "set-url",
        "origin",
        clone_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc2.communicate()


async def checkout_branch(repo_path: str, branch: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        "checkout",
        branch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Checkout failed: {stderr.decode().strip()}")


async def pull_latest(repo_path: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        "pull",
        "--ff-only",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Pull failed: {stderr.decode().strip()}")


async def get_current_commit(repo_path: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return stdout.decode().strip()
    return None
