from app.config import Settings


def test_chat_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.chat_model == "us.anthropic.claude-sonnet-4-6"
    assert s.chat_max_tool_calls == 15
    assert s.chat_timeout_seconds == 120
    assert s.chat_max_response_tokens == 4096
    assert s.chat_thinking_budget_tokens == 2048


def test_summary_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.summary_model == "us.anthropic.claude-sonnet-4-6"
    assert s.summary_max_tokens == 512
    assert s.summary_source_line_cap == 200
    assert s.summary_neighbor_limit == 20
