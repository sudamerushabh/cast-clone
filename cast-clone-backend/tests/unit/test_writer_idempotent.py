"""Tests for MERGE-based idempotent writer and NaN/inf sanitation (CHAN-65, CHAN-66).

The writer must:
  * Use MERGE (not CREATE) so that rerunning produces no duplicates.
  * Sanitize NaN/Infinity in node and edge properties — Neo4j's Bolt protocol
    rejects these values outright.

Neo4j itself is not exercised here; we mock the async driver/session and assert
on the Cypher string and the sanitized parameters.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.services.neo4j import Neo4jGraphStore, _sanitize_props


class _FakeSession:
    """Minimal async-context-manager stand-in for a Neo4j AsyncSession."""

    def __init__(self, cnt: int = 1) -> None:
        self.run = AsyncMock()
        # session.run returns a result whose .single() returns {"cnt": N}.
        result = MagicMock()
        result.single = AsyncMock(return_value={"cnt": cnt})
        self.run.return_value = result
        self.cypher_calls: list[tuple[str, dict[str, Any]]] = []

        async def _capture(cypher: str, params: dict[str, Any] | None = None) -> Any:
            self.cypher_calls.append((cypher, params or {}))
            return result

        self.run.side_effect = _capture

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _FakeDriver:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def session(self, database: str = "neo4j") -> _FakeSession:  # noqa: ARG002
        sess = _FakeSession()
        self.sessions.append(sess)
        return sess


@pytest.mark.asyncio
async def test_writer_rerunning_does_not_duplicate_nodes() -> None:
    """Two back-to-back writes of the same node batch both emit MERGE Cypher."""
    driver = _FakeDriver()
    store = Neo4jGraphStore(driver=driver)  # type: ignore[arg-type]

    nodes = [
        GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
        ),
    ]

    await store.write_nodes_batch(nodes, app_name="proj-1")
    await store.write_nodes_batch(nodes, app_name="proj-1")

    assert len(driver.sessions) == 2, "expected two session invocations (one per call)"
    for sess in driver.sessions:
        cypher, params = sess.cypher_calls[0]
        low = cypher.lower()
        assert "merge" in low, f"expected MERGE in Cypher, got: {cypher}"
        # A naked CREATE (outside an ON CREATE clause) would be a regression.
        assert "create (" not in low.replace(" ", "") or "oncreate" in low
        assert params["batch"][0]["fqn"] == "com.example.UserService"


@pytest.mark.asyncio
async def test_writer_sanitizes_nan_in_node_props_before_send() -> None:
    """The Cypher params must not contain NaN/Inf values."""
    driver = _FakeDriver()
    store = Neo4jGraphStore(driver=driver)  # type: ignore[arg-type]

    nodes = [
        GraphNode(
            fqn="com.example.Dirty",
            name="Dirty",
            kind=NodeKind.CLASS,
            properties={
                "cohesion": float("nan"),
                "coupling": float("inf"),
                "score": -1.5,
            },
        )
    ]

    await store.write_nodes_batch(nodes, app_name="proj-1")

    batch = driver.sessions[0].cypher_calls[0][1]["batch"]
    props = batch[0]["props"]
    assert props["cohesion"] is None
    assert props["coupling"] is None
    assert props["score"] == -1.5


def test_sanitize_replaces_nan_with_none() -> None:
    out = _sanitize_props({"x": float("nan"), "y": 1.0})
    assert out == {"x": None, "y": 1.0}


def test_sanitize_replaces_inf_with_none() -> None:
    out = _sanitize_props({"pos": float("inf"), "neg": float("-inf")})
    assert out == {"pos": None, "neg": None}


def test_sanitize_preserves_normal_values() -> None:
    payload = {
        "s": "hello",
        "n": 42,
        "f": 3.14,
        "b": True,
        "none": None,
        "lst": [1, 2, 3],
    }
    assert _sanitize_props(payload) == payload


def test_sanitize_handles_nested_dicts_if_supported() -> None:
    nested = {
        "stats": {
            "avg_complexity": float("nan"),
            "max_complexity": 42,
            "ratios": [1.0, float("inf"), 0.5],
        },
        "healthy": True,
    }
    out = _sanitize_props(nested)
    assert out["stats"]["avg_complexity"] is None
    assert out["stats"]["max_complexity"] == 42
    assert out["stats"]["ratios"] == [1.0, None, 0.5]
    assert out["healthy"] is True
    # Confirm no residual NaN/Inf anywhere.
    import json

    serialized = json.dumps(out)
    assert "NaN" not in serialized
    assert "Infinity" not in serialized


def test_sanitize_leaves_source_dict_unmodified() -> None:
    src = {"x": float("nan")}
    _ = _sanitize_props(src)
    assert math.isnan(src["x"])  # original untouched


@pytest.mark.asyncio
async def test_edge_writer_sanitizes_props() -> None:
    """NaN/Inf in edge properties are stripped before the Cypher call."""
    driver = _FakeDriver()
    store = Neo4jGraphStore(driver=driver)  # type: ignore[arg-type]

    edges = [
        GraphEdge(
            source_fqn="a",
            target_fqn="b",
            kind=EdgeKind.CALLS,
            confidence=Confidence.HIGH,
            evidence="tree-sitter",
            properties={"weight": float("nan"), "count": 5},
        )
    ]

    await store.write_edges_batch(edges, app_name="proj-1")

    params = driver.sessions[0].cypher_calls[0][1]
    props = params["batch"][0]["properties"]
    assert props["weight"] is None
    assert props["count"] == 5
