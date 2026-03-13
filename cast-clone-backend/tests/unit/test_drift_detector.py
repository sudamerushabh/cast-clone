"""Tests for architecture drift detection."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.pr_analysis.drift_detector import DriftDetector
from app.pr_analysis.models import ChangedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(fqn: str = "com.app.Svc.method") -> ChangedNode:
    return ChangedNode(
        fqn=fqn,
        name="method",
        type="Function",
        path="Svc.java",
        line=1,
        end_line=10,
        language="java",
        change_type="modified",
    )


def _mock_store() -> AsyncMock:
    """Return an AsyncMock that satisfies the GraphStore interface."""
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDriftDetectorNoChanges:
    @pytest.mark.asyncio
    async def test_no_changed_nodes_returns_empty_report(self) -> None:
        store = _mock_store()
        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(changed_nodes=[])

        assert not report.has_drift
        assert report.potential_new_module_deps == []
        assert report.circular_deps_affected == []
        assert report.new_files_outside_modules == []
        store.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_modules_found_returns_empty_report(self) -> None:
        store = _mock_store()
        # First query (module lookup) returns nothing
        store.query.return_value = []
        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(changed_nodes=[_make_node()])

        assert not report.has_drift
        store.query.assert_called_once()


class TestDriftDetectorNewDeps:
    @pytest.mark.asyncio
    async def test_new_cross_module_dep_detected(self) -> None:
        store = _mock_store()

        module_result: list[dict[str, Any]] = [
            {
                "module_fqn": "com.app.service",
                "module_name": "service",
                "changed_nodes_in_module": ["com.app.Svc.method"],
            }
        ]
        dep_result: list[dict[str, Any]] = [
            {"from_module": "service", "to_module": "repository"}
        ]
        cycle_result: list[dict[str, Any]] = []

        store.query.side_effect = [module_result, dep_result, cycle_result]

        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(changed_nodes=[_make_node()])

        assert report.has_drift
        assert len(report.potential_new_module_deps) == 1
        assert report.potential_new_module_deps[0].from_module == "service"
        assert report.potential_new_module_deps[0].to_module == "repository"
        assert report.circular_deps_affected == []


class TestDriftDetectorCircularDeps:
    @pytest.mark.asyncio
    async def test_circular_dep_detected(self) -> None:
        store = _mock_store()

        module_result: list[dict[str, Any]] = [
            {
                "module_fqn": "com.app.service",
                "module_name": "service",
                "changed_nodes_in_module": ["com.app.Svc.method"],
            }
        ]
        dep_result: list[dict[str, Any]] = []
        cycle_result: list[dict[str, Any]] = [
            {"cycle": ["service", "controller", "service"]}
        ]

        store.query.side_effect = [module_result, dep_result, cycle_result]

        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(changed_nodes=[_make_node()])

        assert report.has_drift
        assert report.potential_new_module_deps == []
        assert len(report.circular_deps_affected) == 1
        assert report.circular_deps_affected[0] == [
            "service",
            "controller",
            "service",
        ]


class TestDriftDetectorNewFiles:
    @pytest.mark.asyncio
    async def test_new_files_outside_modules(self) -> None:
        store = _mock_store()
        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(
            changed_nodes=[],
            new_files=["src/orphan/Util.java", "src/misc/Helper.java"],
        )

        # No changed nodes so no graph queries, but new_files passed through
        assert report.has_drift
        assert len(report.new_files_outside_modules) == 2
        assert "src/orphan/Util.java" in report.new_files_outside_modules

    @pytest.mark.asyncio
    async def test_combined_drift_and_new_files(self) -> None:
        store = _mock_store()

        module_result: list[dict[str, Any]] = [
            {
                "module_fqn": "com.app.service",
                "module_name": "service",
                "changed_nodes_in_module": ["com.app.Svc.method"],
            }
        ]
        dep_result: list[dict[str, Any]] = [
            {"from_module": "service", "to_module": "util"}
        ]
        cycle_result: list[dict[str, Any]] = []

        store.query.side_effect = [module_result, dep_result, cycle_result]

        detector = DriftDetector(store, app_name="test-app")
        report = await detector.detect_drift(
            changed_nodes=[_make_node()],
            new_files=["src/orphan/Util.java"],
        )

        assert report.has_drift
        assert len(report.potential_new_module_deps) == 1
        assert len(report.new_files_outside_modules) == 1
