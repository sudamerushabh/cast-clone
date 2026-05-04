"""Blueprint prefix resolution helpers (M4 Task 5)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.models.enums import NodeKind
from app.models.graph import SymbolGraph

# Blueprint("name", __name__, url_prefix="/x")
_BLUEPRINT_CTOR_RE = re.compile(
    r"Blueprint\([^)]*?url_prefix\s*=\s*[\"']([^\"']+)[\"']"
)
# register_blueprint(bp_var, url_prefix="/x")
_REGISTER_RE = re.compile(
    r"register_blueprint\(\s*(\w+)\s*(?:,[^)]*?url_prefix\s*=\s*[\"']([^\"']+)[\"'])?"
)


def _extract_constructor_prefix(raw_value: str) -> str | None:
    match = _BLUEPRINT_CTOR_RE.search(raw_value)
    return match.group(1) if match else None


def _scan_registration_calls(project_root: str) -> dict[str, str]:
    """Walk every .py file under project_root and collect register_blueprint calls.

    Returns a map of blueprint variable name -> registration-time url_prefix.
    Silently skips files we cannot read.
    """
    registrations: dict[str, str] = {}
    root = Path(project_root)
    if not root.exists():
        return registrations
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in _REGISTER_RE.finditer(text):
                var_name = match.group(1)
                prefix = match.group(2)
                if prefix is not None:
                    registrations[var_name] = prefix
    return registrations


def resolve_blueprint_prefixes(graph: SymbolGraph, project_root: str) -> dict[str, str]:
    """Return ``{blueprint_variable_name: effective_url_prefix}``.

    Registration-time prefix wins over construction-time prefix. Blueprints
    with no prefix at all are omitted from the map (callers treat this as "").
    """
    constructor_prefixes: dict[str, str] = {}
    for node in graph.nodes.values():
        if node.kind != NodeKind.FIELD or node.language != "python":
            continue
        raw = node.properties.get("value", "")
        if "Blueprint(" not in raw:
            continue
        ctor_prefix = _extract_constructor_prefix(raw)
        if ctor_prefix is not None:
            constructor_prefixes[node.name] = ctor_prefix

    registration_prefixes = _scan_registration_calls(project_root)

    merged: dict[str, str] = {}
    for var in set(constructor_prefixes) | set(registration_prefixes):
        if var in registration_prefixes:
            merged[var] = registration_prefixes[var]
        else:
            merged[var] = constructor_prefixes[var]
    return merged
