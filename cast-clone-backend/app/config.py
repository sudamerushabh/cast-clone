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

    # Analysis defaults
    scip_timeout: int = 600
    total_analysis_timeout: int = 3600
    max_traversal_depth: int = 15
    treesitter_workers: int | None = None  # None = os.cpu_count()
    log_level: str = "info"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
