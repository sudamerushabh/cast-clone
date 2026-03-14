from app.config import Settings


def test_mcp_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.mcp_port == 8090
    assert s.mcp_api_key_cache_ttl_seconds == 300
    assert s.mcp_last_used_batch_seconds == 60
