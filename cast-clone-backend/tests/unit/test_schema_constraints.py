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
    """Every graph NodeKind -> Neo4j label has a corresponding constraint.

    NODE_LABELS_UNIQUE_KEY is derived from _KIND_TO_LABEL, so this equality
    guards against drift if the derivation is ever broken.
    """
    labels_from_kinds = set(_KIND_TO_LABEL.values())
    constrained_labels = set(NODE_LABELS_UNIQUE_KEY.keys())
    assert constrained_labels == labels_from_kinds, (
        f"labels mismatch: {labels_from_kinds ^ constrained_labels}"
    )


def test_every_constraint_uses_composite_id_key() -> None:
    """Uniqueness must be on the composite `_id`, not on `fqn`.

    ``fqn`` collides across projects; ``_id = f"{app_name}::{fqn}"`` does not.
    """
    for label, key in NODE_LABELS_UNIQUE_KEY.items():
        assert key == "_id", (
            f"label {label} uses {key!r} as UNIQUE key; must be '_id' to "
            f"prevent cross-project MERGE collapse"
        )


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


@pytest.mark.asyncio
async def test_constraint_failure_raises_startup_error() -> None:
    """A neo4j ClientError during CREATE CONSTRAINT must fail startup.

    Existing duplicate data (e.g. from a pre-composite-_id pipeline) would
    surface as a ClientError. Swallowing it would let the server boot with
    a MERGE writer that can no longer deduplicate, so the failure must
    propagate as a RuntimeError with clear ops guidance.
    """
    from neo4j.exceptions import ClientError

    class _FailingSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__()

            async def _raise(stmt: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ARG001
                raise ClientError("existing duplicate node violates constraint")

            self.run.side_effect = _raise

    class _FailingDriver:
        def __init__(self) -> None:
            self.session_instance = _FailingSession()

        def session(self, database: str = "neo4j") -> _FailingSession:  # noqa: ARG002
            return self.session_instance

    driver = _FailingDriver()
    with pytest.raises(RuntimeError, match="dedupe_neo4j_nodes.py"):
        await ensure_schema_constraints(driver)  # type: ignore[arg-type]
