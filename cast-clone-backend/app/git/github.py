"""GitHub platform client for webhook parsing and diff fetching."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlparse

import httpx

from app.git.base import CommentResult, GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_RELEVANT_ACTIONS = {"opened", "synchronize", "closed", "reopened"}


def _normalize_action(action: str, merged: bool) -> str:
    """Normalize GitHub PR action to canonical form."""
    if action == "closed" and merged:
        return "merged"
    if action == "synchronize":
        return "updated"
    return action


class GitHubPlatformClient(GitPlatformClient):
    """GitHub webhook parsing and API client."""

    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-github-event", "")
        if event_type != "pull_request":
            return None

        payload = json.loads(body)
        action = payload.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        pr = payload["pull_request"]
        merged = pr.get("merged", False)

        return PullRequestEvent(
            platform=GitPlatform.github,
            repo_url=payload["repository"]["html_url"],
            pr_number=pr["number"],
            pr_title=pr["title"],
            pr_description=pr.get("body"),
            author=pr["user"]["login"],
            source_branch=pr["head"]["ref"],
            target_branch=pr["base"]["ref"],
            action=_normalize_action(action, merged),
            commit_sha=pr["head"]["sha"],
            created_at=pr["created_at"],
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        signature_header = headers.get("x-hub-signature-256")
        if not signature_header:
            return False

        if not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        received = signature_header[len("sha256=") :]
        return hmac.compare_digest(expected, received)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        parsed = urlparse(repo_url)
        # path like /owner/repo or /owner/repo.git
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        owner, repo = path_parts[0], path_parts[1]

        api_base = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        files: list[FileDiff] = []
        page = 1

        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{api_base}/pulls/{pr_number}/files",
                    headers=headers,
                    params={"per_page": 100, "page": page},
                )
                resp.raise_for_status()
                page_files = resp.json()

                if not page_files:
                    break

                for f in page_files:
                    hunks = parse_patch_hunks(f.get("patch"))
                    status = f.get("status", "modified")
                    files.append(
                        FileDiff(
                            path=f["filename"],
                            status=status,
                            old_path=f.get("previous_filename"),
                            additions=f.get("additions", 0),
                            deletions=f.get("deletions", 0),
                            hunks=hunks,
                        )
                    )

                if len(page_files) < 100:
                    break
                page += 1

        total_add = sum(f.additions for f in files)
        total_del = sum(f.deletions for f in files)

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )

    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        owner, repo = path_parts[0], path_parts[1]

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body})
            resp.raise_for_status()
            data = resp.json()

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=data["html_url"],
            platform="github",
        )
