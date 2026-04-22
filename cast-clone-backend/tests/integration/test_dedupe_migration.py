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
        _FakeRecord({"c": 0}),  # count_null_app_name
        _FakeRecord({"dup_count": 3}),  # count_duplicates
        _FakeRecord({"deleted": 3}),  # first batch deletes 3
        _FakeRecord({"deleted": 0}),  # second batch: nothing left -> exit
    ]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Class", dry_run=False, batch_size=1000
    )

    assert found == 3
    assert deleted == 3

    # 1 null-count + 1 dup-count + 2 delete cypher runs
    assert len(calls) == 4
    count_cypher, _ = calls[1]
    delete_cypher, delete_params = calls[2]

    assert "MATCH (n:`Class`)" in count_cypher
    assert "collect(n) AS nodes" in count_cypher
    assert "app_name IS NOT NULL" in count_cypher
    assert "MATCH (n:`Class`)" in delete_cypher
    assert "app_name IS NOT NULL" in delete_cypher
    # Slice [1..] preserves nodes[0] and only deletes the rest.
    assert "nodes[1..] AS dup" in delete_cypher
    assert "DETACH DELETE dup" in delete_cypher
    assert delete_params == {"batch_size": 1000}


@pytest.mark.asyncio
async def test_dry_run_does_not_delete() -> None:
    """--dry-run runs the COUNT query but never issues DETACH DELETE."""
    results = [
        _FakeRecord({"c": 0}),  # count_null_app_name
        _FakeRecord({"dup_count": 7}),  # count_duplicates
    ]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Function", dry_run=True, batch_size=1000
    )

    assert found == 7
    assert deleted == 0
    assert len(calls) == 2
    dup_cypher, _ = calls[1]
    assert "DETACH DELETE" not in dup_cypher
    assert "RETURN sum(size(nodes) - 1)" in dup_cypher
    assert "app_name IS NOT NULL" in dup_cypher


@pytest.mark.asyncio
async def test_labels_iterated_match_node_labels() -> None:
    """``run()`` walks every label in NODE_LABELS_UNIQUE_KEY exactly once."""
    visited: list[str] = []

    async def fake_dedupe_label(
        _driver: Any, label: str, **_kw: Any
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
        _driver: Any, label: str, **_kw: Any
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
    results = [
        _FakeRecord({"c": 0}),  # count_null_app_name
        _FakeRecord({"dup_count": 0}),  # count_duplicates
    ]
    driver, calls = _make_driver(results)

    found, deleted = await dedupe.dedupe_label(
        driver, "Module", dry_run=False, batch_size=1000
    )

    assert (found, deleted) == (0, 0)
    # Only the null-count + dup-count queries run; no delete cypher.
    assert len(calls) == 2
    assert all("DETACH DELETE" not in call[0] for call in calls)


@pytest.mark.asyncio
async def test_null_app_name_nodes_not_merged() -> None:
    """Nodes with ``app_name IS NULL`` are excluded from the dedupe Cypher and
    surfaced via a warning log so operators can triage cross-tenant leftovers.

    Scenario: two legacy records share the same ``fqn`` but live in different
    projects, and both have ``app_name = NULL``. Merging them would collapse
    tenants, so the WHERE clause must filter them out and the warning must fire.
    """
    # Two null-app_name nodes exist; zero non-null duplicates to delete.
    results = [
        _FakeRecord({"c": 2}),  # count_null_app_name -> 2 null rows
        _FakeRecord({"dup_count": 0}),  # count_duplicates (filtered)
    ]
    driver, calls = _make_driver(results)

    # Structlog's stdlib integration may not be configured under pytest, so
    # assert on the logger invocation directly instead of going through caplog.
    warn_mock = AsyncMock(return_value=None)
    with patch.object(dedupe.logger, "awarning", warn_mock):
        found, deleted = await dedupe.dedupe_label(
            driver, "Class", dry_run=False, batch_size=1000
        )

    # No duplicates after filtering null-app_name; nothing deleted.
    assert (found, deleted) == (0, 0)

    # Warning must fire naming the label and null count.
    warn_mock.assert_awaited_once()
    event, *_ = warn_mock.await_args.args
    assert event == "dedupe.null_app_name_nodes_skipped"
    kwargs = warn_mock.await_args.kwargs
    assert kwargs == {"label": "Class", "count": 2}

    # Both the null-count query and the dup-count query must filter out nulls
    # from the grouping — the dup query's WHERE clause must include it.
    null_count_cypher, _ = calls[0]
    dup_count_cypher, _ = calls[1]
    assert "n.app_name IS NULL" in null_count_cypher
    assert "app_name IS NOT NULL" in dup_count_cypher
    # No DETACH DELETE was issued (nothing past the null-count + dup-count).
    assert all("DETACH DELETE" not in call[0] for call in calls)


@pytest.mark.asyncio
async def test_delete_duplicates_cypher_filters_null_app_name() -> None:
    """Direct test of ``delete_duplicates``: its Cypher must include
    ``app_name IS NOT NULL`` so null-app_name nodes cannot be cross-tenant
    merged even when the function is invoked in isolation."""
    results = [_FakeRecord({"deleted": 0})]
    driver, calls = _make_driver(results)

    deleted = await dedupe.delete_duplicates(
        driver, "Class", batch_size=500
    )

    assert deleted == 0
    assert len(calls) == 1
    cypher, params = calls[0]
    assert "app_name IS NOT NULL" in cypher
    assert "DETACH DELETE dup" in cypher
    assert params == {"batch_size": 500}
