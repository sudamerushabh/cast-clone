"""Tests for Neo4j UNIQUE constraint bootstrapping (CHAN-64)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.graph import _KIND_TO_LABEL
from app.services.neo4j import (
    NODE_LABELS_UNIQUE_KEY,
    build_constraint_statements,
    ensure_schema_constraints,
)


class _FakeSession:
    """Minimal async-context-manager stand-in for a Neo4j AsyncSession."""

    def __init__(self) -> None:
        self.run = AsyncMock()
        self.statements: list[str] = []

        async def _capture(stmt: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ARG001
            self.statements.append(stmt)
            return MagicMock()

        self.run.side_effect = _capture

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _FakeDriver:
    def __init__(self) -> None:
        self.session_instance = _FakeSession()

    def session(self, database: str = "neo4j") -> _FakeSession:  # noqa: ARG002
        return self.session_instance


def test_build_constraint_statements_emits_if_not_exists() -> None:
    """Every generated statement uses IF NOT EXISTS — safe to re-run."""
    stmts = build_constraint_statements()
    assert stmts, "expected at least one constraint"
    for s in stmts:
        assert "CREATE CONSTRAINT" in s
        assert "IF NOT EXISTS" in s, f"missing idempotency guard: {s}"
        assert "IS UNIQUE" in s


def test_all_node_labels_covered() -> None:
    """Every graph NodeKind -> Neo4j label has a corresponding constraint."""
    labels_from_kinds = set(_KIND_TO_LABEL.values())
    constrained_labels = set(NODE_LABELS_UNIQUE_KEY.keys())
    missing = labels_from_kinds - constrained_labels
    assert not missing, f"labels without UNIQUE constraint: {missing}"


def test_constraint_statements_target_expected_labels() -> None:
    stmts = build_constraint_statements()
    for label, key in NODE_LABELS_UNIQUE_KEY.items():
        expected_snippet = f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        assert any(expected_snippet in s for s in stmts), (
            f"no constraint targets :{label}({key})"
        )


@pytest.mark.asyncio
async def test_ensure_schema_constraints_runs_every_statement() -> None:
    """ensure_schema_constraints issues one session.run per constraint stmt."""
    driver = _FakeDriver()
    await ensure_schema_constraints(driver)  # type: ignore[arg-type]

    expected = build_constraint_statements()
    assert driver.session_instance.statements == expected


@pytest.mark.asyncio
async def test_ensure_schema_constraints_is_idempotent() -> None:
    """Calling twice runs the same IF NOT EXISTS statements again safely."""
    driver = _FakeDriver()
    await ensure_schema_constraints(driver)  # type: ignore[arg-type]
    first = list(driver.session_instance.statements)
    driver.session_instance.statements.clear()
    await ensure_schema_constraints(driver)  # type: ignore[arg-type]
    second = list(driver.session_instance.statements)
    assert first == second
    for stmt in second:
        assert "IF NOT EXISTS" in stmt
