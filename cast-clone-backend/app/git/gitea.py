"""Gitea platform client for webhook parsing and diff fetching."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlparse

import httpx

from app.git.base import GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_RELEVANT_ACTIONS = {"opened", "synchronized", "closed", "reopened"}


def _normalize_action(action: str, merged: bool) -> str:
    """Normalize Gitea PR action to canonical form."""
    if action == "closed" and merged:
        return "merged"
    if action == "synchronized":
        return "updated"
    return action


class GiteaPlatformClient(GitPlatformClient):
    """Gitea webhook parsing and API client."""

    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-gitea-event", "")
        if event_type != "pull_request":
            return None

        payload = json.loads(body)
        action = payload.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        pr = payload["pull_request"]
        merged = pr.get("merged", False)
        repo = payload["repository"]

        return PullRequestEvent(
            platform=GitPlatform.gitea,
            repo_url=repo["html_url"],
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
        signature = headers.get("x-gitea-signature")
        if not signature:
            return False

        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        owner, repo = path_parts[0], path_parts[1]

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        api_base = f"{base_url}/api/v1/repos/{owner}/{repo}"
        headers = {"Authorization": f"token {token}"}

        files: list[FileDiff] = []
        page = 1

        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{api_base}/pulls/{pr_number}/files",
                    headers=headers,
                    params={"limit": 50, "page": page},
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

                if len(page_files) < 50:
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
