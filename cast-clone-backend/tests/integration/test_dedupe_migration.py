"""Tests for the one-shot Neo4j dedupe migration script (CHAN-68).

No real Neo4j: the async driver / session / result are mocked so the tests
only assert on the Cypher statements and params the script emits.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.neo4j import NODE_LABELS_UNIQUE_KEY
from scripts import dedupe_neo4j_nodes as dedupe


class _FakeRecord:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class _FakeResult:
    def __init__(self, record: _FakeRecord | None) -> None:
        self._record = record

    async def single(self) -> _FakeRecord | None:
        return self._record


class _FakeSession:
    """Minimal stand-in for ``neo4j.AsyncSession``.

    Records every ``run(cypher, params)`` call and returns queued results in
    order. Supports ``async with`` by returning itself.
    """

    def __init__(
        self,
        results: list[_FakeRecord | None],
        calls: list[tuple[str, dict[str, Any]]],
    ) -> None:
        # Shared lists so every session/driver.session() call drains the same
        # queue and appends to the same call log. The script opens a new
        # session per query, so state must survive session close.
        self._results = results
        self._calls = calls

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def run(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> _FakeResult:
        self._calls.append((cypher, params or {}))
        if not self._results:
            return _FakeResult(None)
        return _FakeResult(self._results.pop(0))


def _make_driver(
    results: list[_FakeRecord | None],
) -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Build a fake driver whose ``session(...)`` replays ``results``."""
    calls: list[tuple[str, dict[str, Any]]] = []
    shared_results = list(results)
    driver = MagicMock()
    driver.session = MagicMock(
        side_effect=lambda database=None: _FakeSession(shared_results, calls)
    )
    return driver, calls


@pytest.mark.asyncio
async def test_dedupe_preserves_first_node() -> None:
    """For a label with 3 duplicate buckets, DETACH DELETE runs until drained."""
    results = [
        _FakeRecord({"dup_count": 3}),  # count_duplicates
        _FakeRecord({"deleted": 3}),  # first batch deletes 3
        _FakeRecord({"deleted": 0}),  # second batch: nothing left -> exit
    ]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Class", "fqn", dry_run=False, batch_size=1000
    )

    assert found == 3
    assert deleted == 3

    # 1 count + 2 delete cypher runs
    assert len(calls) == 3
    count_cypher, _ = calls[0]
    delete_cypher, delete_params = calls[1]

    assert "MATCH (n:`Class`)" in count_cypher
    assert "collect(n) AS nodes" in count_cypher
    assert "MATCH (n:`Class`)" in delete_cypher
    # Slice [1..] preserves nodes[0] and only deletes the rest.
    assert "nodes[1..] AS dup" in delete_cypher
    assert "DETACH DELETE dup" in delete_cypher
    assert delete_params == {"batch_size": 1000}


@pytest.mark.asyncio
async def test_dry_run_does_not_delete() -> None:
    """--dry-run runs the COUNT query but never issues DETACH DELETE."""
    results = [_FakeRecord({"dup_count": 7})]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Function", "fqn", dry_run=True, batch_size=1000
    )

    assert found == 7
    assert deleted == 0
    assert len(calls) == 1
    cypher, _ = calls[0]
    assert "DETACH DELETE" not in cypher
    assert "RETURN sum(size(nodes) - 1)" in cypher


@pytest.mark.asyncio
async def test_labels_iterated_match_node_labels() -> None:
    """``run()`` walks every label in NODE_LABELS_UNIQUE_KEY exactly once."""
    visited: list[str] = []

    async def fake_dedupe_label(
        _driver: Any, label: str, _key: str, **_kw: Any
    ) -> tuple[int, int]:
        visited.append(label)
        return 0, 0

    async def fake_init(_settings: Any) -> None:
        return None

    async def fake_close() -> None:
        return None

    with (
        patch.object(dedupe, "init_neo4j", side_effect=fake_init),
        patch.object(dedupe, "close_neo4j", side_effect=fake_close),
        patch.object(dedupe, "get_driver", return_value=MagicMock()),
        patch.object(dedupe, "dedupe_label", side_effect=fake_dedupe_label),
    ):
        results = await dedupe.run(dry_run=True, label_filter=None, batch_size=1000)

    assert visited == list(NODE_LABELS_UNIQUE_KEY.keys())
    assert set(results.keys()) == set(NODE_LABELS_UNIQUE_KEY.keys())


@pytest.mark.asyncio
async def test_label_filter_runs_only_requested_label() -> None:
    """--label X restricts the run to a single label."""
    visited: list[str] = []

    async def fake_dedupe_label(
        _driver: Any, label: str, _key: str, **_kw: Any
    ) -> tuple[int, int]:
        visited.append(label)
        return 0, 0

    with (
        patch.object(dedupe, "init_neo4j", new=AsyncMock(return_value=None)),
        patch.object(dedupe, "close_neo4j", new=AsyncMock(return_value=None)),
        patch.object(dedupe, "get_driver", return_value=MagicMock()),
        patch.object(dedupe, "dedupe_label", side_effect=fake_dedupe_label),
    ):
        await dedupe.run(dry_run=True, label_filter="Class", batch_size=1000)

    assert visited == ["Class"]


@pytest.mark.asyncio
async def test_unknown_label_filter_raises() -> None:
    with pytest.raises(ValueError, match="Unknown label"):
        await dedupe.run(dry_run=True, label_filter="NotARealLabel", batch_size=1000)


@pytest.mark.asyncio
async def test_idempotent_second_run_reports_zero() -> None:
    """Running the dedupe a second time finds zero duplicates, zero deletes."""
    results = [_FakeRecord({"dup_count": 0})]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Module", "fqn", dry_run=False, batch_size=1000
    )

    assert (found, deleted) == (0, 0)
    # Only the count query runs; no delete cypher.
    assert len(calls) == 1
    assert "DETACH DELETE" not in calls[0][0]
