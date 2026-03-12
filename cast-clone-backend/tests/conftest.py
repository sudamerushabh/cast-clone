"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_java_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "raw-java"


@pytest.fixture
def spring_petclinic_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "spring-petclinic"


@pytest.fixture
def express_app_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "express-app"
