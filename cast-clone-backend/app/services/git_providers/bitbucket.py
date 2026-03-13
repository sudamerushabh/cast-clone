"""Bitbucket Cloud provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class BitbucketProvider(GitProvider):
    @property
    def _api_base(self) -> str:
        if "bitbucket.org" in self.base_url:
            return "https://api.bitbucket.org/2.0"
        return f"{self.base_url}/rest/api/2.0"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user", headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
            username = data.get("username") or data.get("nickname", "")
            avatar = None
            if "links" in data and "avatar" in data["links"]:
                avatar = data["links"]["avatar"].get("href")
            return GitUser(
                username=username,
                display_name=data.get("display_name"),
                avatar_url=avatar,
            )

    async def list_repos(
        self, page: int = 1, per_page: int = 30, search: str | None = None
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "role": "member",
                "pagelen": per_page,
                "page": page,
            }
            if search:
                params["q"] = f'name ~ "{search}"'
            resp = await client.get(
                f"{self._api_base}/repositories",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("values", [])
            has_more = data.get("next") is not None

            repos = []
            for r in items:
                clone_url = ""
                for link in r.get("links", {}).get("clone", []):
                    if link.get("name") == "https":
                        clone_url = link["href"]
                        break
                repos.append(
                    GitRepo(
                        full_name=r["full_name"],
                        clone_url=clone_url,
                        default_branch=r.get("mainbranch", {}).get(
                            "name", "main"
                        ),
                        description=r.get("description"),
                        language=r.get("language"),
                        is_private=r.get("is_private", False),
                    )
                )
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repositories/{full_name}",
                headers=self._headers,
            )
            resp.raise_for_status()
            r = resp.json()
            clone_url = ""
            for link in r.get("links", {}).get("clone", []):
                if link.get("name") == "https":
                    clone_url = link["href"]
                    break
            return GitRepo(
                full_name=r["full_name"],
                clone_url=clone_url,
                default_branch=r.get("mainbranch", {}).get("name", "main"),
                description=r.get("description"),
                language=r.get("language"),
                is_private=r.get("is_private", False),
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repositories/{full_name}/refs/branches",
                headers=self._headers,
                params={"pagelen": 100},
            )
            resp.raise_for_status()
            data = resp.json()
            return [b["name"] for b in data.get("values", [])]
