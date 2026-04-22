"""Integration test fixtures using testcontainers.

Provides real Neo4j and PostgreSQL instances for testing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models.context import AnalysisContext

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
PETCLINIC_DIR = FIXTURE_DIR / "spring-petclinic"


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def _ensure_python_extractor():
    """Register the PythonExtractor once per session for all integration tests."""
    from app.stages.treesitter.extractors import register_extractor
    from app.stages.treesitter.extractors.python import PythonExtractor

    register_extractor("python", PythonExtractor())
    yield


@pytest.fixture
def petclinic_path() -> Path:
    """Path to the Spring PetClinic test fixture."""
    assert PETCLINIC_DIR.exists(), f"PetClinic fixture not found at {PETCLINIC_DIR}"
    return PETCLINIC_DIR


@pytest.fixture
def analysis_context() -> AnalysisContext:
    """Create a fresh AnalysisContext for testing."""
    return AnalysisContext(project_id="test-project")
