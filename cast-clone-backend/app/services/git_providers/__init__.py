"""Git provider adapters for GitHub, GitLab, Gitea, Bitbucket."""

from __future__ import annotations

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


def create_provider(provider: str, base_url: str, token: str) -> GitProvider:
    if provider == "github":
        from app.services.git_providers.github import GitHubProvider

        return GitHubProvider(base_url, token)
    elif provider == "gitlab":
        from app.services.git_providers.gitlab import GitLabProvider

        return GitLabProvider(base_url, token)
    elif provider == "gitea":
        from app.services.git_providers.gitea import GiteaProvider

        return GiteaProvider(base_url, token)
    elif provider == "bitbucket":
        from app.services.git_providers.bitbucket import BitbucketProvider

        return BitbucketProvider(base_url, token)
    else:
        raise ValueError(f"Unknown provider: {provider}")


__all__ = ["GitProvider", "GitRepo", "GitUser", "create_provider"]
