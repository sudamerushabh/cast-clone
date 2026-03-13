"""Report types for AI agent pipeline outputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class SummaryResult:
    """Final summary produced by the supervisor agent."""

    summary: str
    tokens_used: int
    agents_run: int = 0
    agents_failed: int = 0
    total_duration_ms: int = 0


@dataclass
class AgentReport:
    """Output from a single sub-agent."""

    role: str
    raw_text: str
    parsed: dict | None = None
    parse_failed: bool = False


@dataclass
class CodeChangeReport:
    """Structured report from a code-change analysis agent."""

    files_analyzed: list[str] = field(default_factory=list)
    functions_changed: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class ArchImpactReport:
    """Structured report from an architecture impact agent."""

    modules_affected: list[str] = field(default_factory=list)
    dependency_changes: list[str] = field(default_factory=list)
    breaking_changes: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class InfraConfigReport:
    """Structured report from an infra/config analysis agent."""

    config_files_changed: list[str] = field(default_factory=list)
    env_vars_added: list[str] = field(default_factory=list)
    env_vars_removed: list[str] = field(default_factory=list)
    infra_risks: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class TestGapReport:
    """Structured report from a test gap analysis agent."""

    untested_changes: list[str] = field(default_factory=list)
    test_files_changed: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    summary: str = ""


def parse_agent_response(role: str, text: str) -> AgentReport:
    """Parse an agent's text response, extracting JSON if present.

    Strategy:
    1. Find all JSON-like blocks via regex, try last match first.
    2. Try the whole text as JSON.
    3. Fallback: return AgentReport with parse_failed=True.
    """
    pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    matches = re.findall(pattern, text, re.DOTALL)

    # Try last match first (agents often put JSON at the end)
    for match in reversed(matches):
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict):
                return AgentReport(role=role, raw_text=text, parsed=parsed)
        except (json.JSONDecodeError, ValueError):
            continue

    # Try whole text as JSON
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict):
            return AgentReport(role=role, raw_text=text, parsed=parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    return AgentReport(role=role, raw_text=text, parse_failed=True)
