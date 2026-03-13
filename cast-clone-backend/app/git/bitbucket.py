"""Bitbucket platform client for webhook parsing and diff fetching."""

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

_EVENT_KEY_MAP = {
    "pullrequest:created": "opened",
    "pullrequest:updated": "updated",
    "pullrequest:fulfilled": "merged",
    "pullrequest:rejected": "closed",
}


class BitbucketPlatformClient(GitPlatformClient):
    """Bitbucket webhook parsing and API client."""

    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_key = headers.get("x-event-key", "")
        action = _EVENT_KEY_MAP.get(event_key)
        if action is None:
            return None

        payload = json.loads(body)
        pr = payload["pullrequest"]
        repo = payload["repository"]

        repo_url = repo["links"]["html"]["href"]
        source = pr["source"]
        destination = pr["destination"]

        return PullRequestEvent(
            platform=GitPlatform.bitbucket,
            repo_url=repo_url,
            pr_number=pr["id"],
            pr_title=pr["title"],
            pr_description=pr.get("description"),
            author=pr["author"]["username"],
            source_branch=source["branch"]["name"],
            target_branch=destination["branch"]["name"],
            action=action,
            commit_sha=source["commit"]["hash"],
            created_at=pr["created_on"],
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        signature_header = headers.get("x-hub-signature")
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
        # path like /workspace/repo
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        workspace, repo = path_parts[0], path_parts[1]

        url: str | None = (
            f"https://api.bitbucket.org/2.0/repositories"
            f"/{workspace}/{repo}/pullrequests/{pr_number}/diffstat"
        )
        headers = {"Authorization": f"Bearer {token}"}

        files: list[FileDiff] = []

        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                for entry in data.get("values", []):
                    new_path = entry.get("new", {})
                    old_path_info = entry.get("old", {})
                    status_str = entry.get("status", "modified")

                    path = (
                        new_path.get("path", "")
                        if new_path
                        else old_path_info.get("path", "")
                    )
                    old_path = (
                        old_path_info.get("path")
                        if status_str == "renamed"
                        else None
                    )

                    files.append(
                        FileDiff(
                            path=path,
                            status=status_str,
                            old_path=old_path,
                            additions=entry.get("lines_added", 0),
                            deletions=entry.get("lines_removed", 0),
                            hunks=[],  # diffstat doesn't include patch text
                        )
                    )

                url = data.get("next")

        total_add = sum(f.additions for f in files)
        total_del = sum(f.deletions for f in files)

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )
