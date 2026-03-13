"""Tests for Phase 5a configuration and schema validation."""
import pytest
from app.config import Settings


class TestPhase5aConfig:
    def test_anthropic_api_key_default_empty(self):
        s = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")
        assert s.anthropic_api_key == ""

    def test_anthropic_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        # Clear lru_cache so Settings picks up new env
        from app.config import get_settings
        get_settings.cache_clear()
        s = Settings()
        assert s.anthropic_api_key == "sk-ant-test-key"
