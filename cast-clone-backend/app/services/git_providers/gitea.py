"""Gitea provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GiteaProvider(GitProvider):
    @property
    def _api_base(self) -> str:
        return f"{self.base_url}/api/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self.token}"}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user", headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["login"],
                display_name=data.get("full_name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self, page: int = 1, per_page: int = 30, search: str | None = None
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            if search:
                resp = await client.get(
                    f"{self._api_base}/repos/search",
                    headers=self._headers,
                    params={
                        "q": search,
                        "page": page,
                        "limit": per_page,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else data
            else:
                resp = await client.get(
                    f"{self._api_base}/user/repos",
                    headers=self._headers,
                    params={"page": page, "limit": per_page},
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
                f"{self._api_base}/repos/{full_name}", headers=self._headers
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
                params={"limit": 100},
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
