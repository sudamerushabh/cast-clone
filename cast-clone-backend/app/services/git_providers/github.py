"""GitHub provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GitHubProvider(GitProvider):
    @property
    def _api_base(self) -> str:
        if self.base_url.rstrip("/") == "https://github.com":
            return "https://api.github.com"
        return f"{self.base_url}/api/v3"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user", headers=self._headers, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["login"],
                display_name=data.get("name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self, page: int = 1, per_page: int = 30, search: str | None = None
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            if search:
                resp = await client.get(
                    f"{self._api_base}/search/repositories",
                    headers=self._headers,
                    params={
                        "q": f"{search} user:@me",
                        "page": page,
                        "per_page": per_page,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                total = data.get("total_count", 0)
                has_more = page * per_page < total
            else:
                resp = await client.get(
                    f"{self._api_base}/user/repos",
                    headers=self._headers,
                    params={
                        "page": page,
                        "per_page": per_page,
                        "sort": "updated",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                items = resp.json()
                has_more = len(items) == per_page

            repos = [
                GitRepo(
                    full_name=r["full_name"],
                    clone_url=r["clone_url"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=r.get("language"),
                    is_private=r.get("private", False),
                )
                for r in items
            ]
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}", headers=self._headers, timeout=10
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["full_name"],
                clone_url=r["clone_url"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=r.get("language"),
                is_private=r.get("private", False),
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}/branches",
                headers=self._headers,
                params={"per_page": 100},
                timeout=15,
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
