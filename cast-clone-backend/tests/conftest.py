"""Shared pytest fixtures for all test modules."""

import os
from pathlib import Path

import pytest

# Default to auth-disabled for the test suite. Individual tests that need to
# exercise auth/authz can override via monkeypatch. This keeps the config
# validator (which now requires SECRET_KEY when AUTH_DISABLED=false) happy
# for tests that don't care about auth.
os.environ.setdefault("AUTH_DISABLED", "true")


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the absolute path to tests/fixtures/."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_java_dir(fixtures_dir: Path) -> Path:
    """Return the path to the raw-java fixture project."""
    return fixtures_dir / "raw-java"


@pytest.fixture
def express_app_dir(fixtures_dir: Path) -> Path:
    """Return the path to the express-app fixture project."""
    return fixtures_dir / "express-app"


@pytest.fixture
def spring_petclinic_dir(fixtures_dir: Path) -> Path:
    """Return the path to the spring-petclinic fixture project."""
    return fixtures_dir / "spring-petclinic"
