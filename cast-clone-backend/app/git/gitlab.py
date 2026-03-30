"""GitLab platform client for webhook parsing and diff fetching."""

from __future__ import annotations

import hmac
import json
from urllib.parse import quote, urlparse

import httpx

from app.git.base import CommentResult, GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_ACTION_MAP = {
    "open": "opened",
    "update": "updated",
    "close": "closed",
    "reopen": "reopened",
    "merge": "merged",
}

_RELEVANT_ACTIONS = set(_ACTION_MAP.keys())


class GitLabPlatformClient(GitPlatformClient):
    """GitLab webhook parsing and API client."""

    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-gitlab-event", "")
        if event_type != "Merge Request Hook":
            return None

        payload = json.loads(body)
        attrs = payload["object_attributes"]
        action = attrs.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        project = payload["project"]

        return PullRequestEvent(
            platform=GitPlatform.gitlab,
            repo_url=project["web_url"],
            pr_number=attrs["iid"],
            pr_title=attrs["title"],
            pr_description=attrs.get("description"),
            author=payload["user"]["username"],
            source_branch=attrs["source_branch"],
            target_branch=attrs["target_branch"],
            action=_ACTION_MAP[action],
            commit_sha=attrs["last_commit"]["id"],
            created_at=attrs["created_at"],
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        token = headers.get("x-gitlab-token")
        if token is None:
            return False
        return hmac.compare_digest(token, secret)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        parsed = urlparse(repo_url)
        # path like /group/subgroup/repo
        project_path = parsed.path.strip("/").removesuffix(".git")
        encoded_path = quote(project_path, safe="")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        api_url = (
            f"{base_url}/api/v4/projects/{encoded_path}"
            f"/merge_requests/{pr_number}/changes"
        )
        headers = {"PRIVATE-TOKEN": token}

        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        files: list[FileDiff] = []
        for change in data.get("changes", []):
            diff_text = change.get("diff", "")
            hunks = parse_patch_hunks(diff_text)

            # Count additions/deletions from the diff text
            additions = 0
            deletions = 0
            for line in diff_text.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1

            if change.get("new_file"):
                status = "added"
            elif change.get("deleted_file"):
                status = "deleted"
            elif change.get("renamed_file"):
                status = "renamed"
            else:
                status = "modified"

            files.append(
                FileDiff(
                    path=change["new_path"],
                    status=status,
                    old_path=(
                        change["old_path"]
                        if change.get("renamed_file")
                        else None
                    ),
                    additions=additions,
                    deletions=deletions,
                    hunks=hunks,
                )
            )

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
        project_path = parsed.path.strip("/").removesuffix(".git")
        encoded_path = quote(project_path, safe="")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        url = (
            f"{base_url}/api/v4/projects/{encoded_path}"
            f"/merge_requests/{pr_number}/notes"
        )
        headers = {"PRIVATE-TOKEN": token}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body})
            resp.raise_for_status()
            data = resp.json()

        comment_url = (
            f"{repo_url}/-/merge_requests/{pr_number}#note_{data['id']}"
        )

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=comment_url,
            platform="gitlab",
        )
