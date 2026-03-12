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
    cors_origins: list[str] = ["http://localhost:3000"]
