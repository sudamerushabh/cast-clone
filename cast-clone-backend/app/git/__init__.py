"""Git platform clients for webhook parsing and diff fetching."""

from __future__ import annotations

from app.git.base import GitPlatformClient


def create_platform_client(platform: str) -> GitPlatformClient:
    """Return the appropriate GitPlatformClient for the given platform name.

    Args:
        platform: One of "github", "gitlab", "bitbucket", "gitea".

    Returns:
        An instance of the corresponding platform client.

    Raises:
        ValueError: If the platform is not supported.
    """
    if platform == "github":
        from app.git.github import GitHubPlatformClient

        return GitHubPlatformClient()
    elif platform == "gitlab":
        from app.git.gitlab import GitLabPlatformClient

        return GitLabPlatformClient()
    elif platform == "bitbucket":
        from app.git.bitbucket import BitbucketPlatformClient

        return BitbucketPlatformClient()
    elif platform == "gitea":
        from app.git.gitea import GiteaPlatformClient

        return GiteaPlatformClient()
    else:
        raise ValueError(f"Unknown git platform: {platform!r}")
