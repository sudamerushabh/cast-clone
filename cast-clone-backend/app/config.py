from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = (
        "postgresql+asyncpg://codelens:codelens@localhost:15432/codelens"
    )
    neo4j_uri: str = "bolt://localhost:17687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "codelens"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "codelens"
    minio_secret_key: str = "codelens123"
    minio_secure: bool = False
    cors_origins: list[str] = ["*"]

    # Security
    secret_key: str = "change-me-in-production"
    auth_disabled: bool = True  # Set AUTH_DISABLED=true to bypass auth (dev/testing)

    # Repository storage
    repo_storage_path: str = "/home/ubuntu/repos"
    git_clone_timeout: int = 600

    # Analysis defaults
    scip_timeout: int = 600
    total_analysis_timeout: int = 3600
    max_traversal_depth: int = 15
    treesitter_workers: int | None = None  # None = os.cpu_count()
    log_level: str = "info"
    # Phase 5a: AI agent pipeline (Bedrock)
    aws_region: str = "us-east-1"
    pr_analysis_model: str = "us.anthropic.claude-sonnet-4-6"
    pr_analysis_supervisor_model: str = "us.anthropic.claude-sonnet-4-6"
    pr_analysis_max_subagents: int = 15
    pr_analysis_max_total_tokens: int = 500_000
    # Phase 5b: AI chat
    chat_model: str = "us.anthropic.claude-sonnet-4-6"
    chat_max_tool_calls: int = 15
    chat_timeout_seconds: int = 120
    chat_max_response_tokens: int = 4096
    chat_thinking_budget_tokens: int = 2048

    # Phase 5b-M2: AI summaries
    summary_model: str = "us.anthropic.claude-sonnet-4-6"
    summary_max_tokens: int = 512
    summary_source_line_cap: int = 200
    summary_neighbor_limit: int = 20

    # Phase 5b-M4: MCP server
    mcp_port: int = 8090
    mcp_api_key_cache_ttl_seconds: int = 300
    mcp_last_used_batch_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
