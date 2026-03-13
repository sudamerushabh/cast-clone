"""GitLab provider adapter."""

from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GitLabProvider(GitProvider):
    @property
    def _api_base(self) -> str:
        return f"{self.base_url}/api/v4"

    @property
    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self.token}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user", headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["username"],
                display_name=data.get("name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self, page: int = 1, per_page: int = 30, search: str | None = None
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "membership": "true",
                "page": page,
                "per_page": per_page,
                "order_by": "updated_at",
            }
            if search:
                params["search"] = search
            resp = await client.get(
                f"{self._api_base}/projects",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            items = resp.json()
            has_more = len(items) == per_page

            repos = [
                GitRepo(
                    full_name=r["path_with_namespace"],
                    clone_url=r["http_url_to_repo"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=None,
                    is_private=r.get("visibility") == "private",
                )
                for r in items
            ]
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        encoded = quote_plus(full_name)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/projects/{encoded}",
                headers=self._headers,
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["path_with_namespace"],
                clone_url=r["http_url_to_repo"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=None,
                is_private=r.get("visibility") == "private",
            )

    async def list_branches(self, full_name: str) -> list[str]:
        encoded = quote_plus(full_name)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/projects/{encoded}/repository/branches",
                headers=self._headers,
                params={"per_page": 100},
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
