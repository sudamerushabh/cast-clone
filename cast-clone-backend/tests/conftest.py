"""Shared pytest fixtures for all test modules."""

from pathlib import Path

import pytest


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
