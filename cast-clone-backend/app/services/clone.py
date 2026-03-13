"""Git clone, checkout, and pull operations."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import structlog

logger = structlog.get_logger()


def sanitize_branch_name(branch: str) -> str:
    """Sanitize a branch name for use as a directory name."""
    sanitized = branch.replace("/", "--")
    sanitized = re.sub(r"[^a-zA-Z0-9._\-]", "-", sanitized)
    return sanitized


def get_branch_clone_path(repo_local_path: str, branch: str) -> str:
    """Get the path where a branch clone should live.

    Layout: /repos/{repo_id}--branches/{sanitized_branch}/
    """
    base = repo_local_path.rstrip("/")
    return f"{base}--branches/{sanitize_branch_name(branch)}"


async def clone_branch_local(
    source_repo_path: str, branch: str, target_dir: str, timeout: int = 300
) -> None:
    """Create a local clone of a specific branch from an existing repo clone.

    Uses `git clone --local --branch <branch>` which hardlinks git objects
    for minimal disk usage.

    Skips if target_dir already exists and contains a .git directory.
    """
    target = Path(target_dir)
    resolved = target.resolve()
    if not str(resolved).startswith(str(target.parent.resolve())):
        raise ValueError(f"Invalid clone target: {target_dir}")

    if target.exists() and (target / ".git").exists():
        logger.info("branch_clone_exists", target=target_dir, branch=branch)
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--local", "--branch", branch,
        source_repo_path, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Branch clone timed out after {timeout}s")

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        raise RuntimeError(f"Clone failed: {error_msg}")

    logger.info("branch_clone_created", target=target_dir, branch=branch)


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


async def fetch_all_refs(repo_path: str) -> None:
    """Fetch all remote refs so local branch clones can find any branch."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        "fetch",
        "--all",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Fetch failed: {stderr.decode().strip()}")


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


async def cleanup_repo_dirs(repo_local_path: str | None) -> None:
    """Remove the repo clone directory and all branch clone directories.

    Removes:
    - {repo_local_path} (main clone)
    - {repo_local_path}--branches/ (all branch clones)
    """
    if not repo_local_path:
        return

    import shutil

    base = Path(repo_local_path)
    branches_dir = Path(f"{repo_local_path}--branches")

    for d in [base, branches_dir]:
        if d.exists() and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            logger.info("repo_dir_removed", path=str(d))


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
