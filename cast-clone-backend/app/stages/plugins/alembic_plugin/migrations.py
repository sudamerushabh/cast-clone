"""Alembic migration plugin.

Parses files under `migrations/versions/*.py` to reconstruct the revision
chain as a DAG:

- Each migration file becomes a CONFIG_FILE node with `revision_id`,
  `down_revision`, and `upgrade_ops` / `downgrade_ops` properties.
- An INHERITS edge from revision -> down_revision encodes the chain.

The parser uses the stdlib `ast` module (not regex) so nested keyword args
inside `op.*` calls don't break extraction.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


@dataclass
class MigrationInfo:
    """Static metadata extracted from a single Alembic migration file.

    Treat as write-once: do not mutate after construction. `frozen` is not
    applied because the list fields would still be mutable in place.
    """

    file_path: Path
    revision_id: str
    down_revision: str | None
    upgrade_ops: list[dict[str, str]]
    downgrade_ops: list[dict[str, str]]


def parse_migration_file(path: Path) -> MigrationInfo | None:
    """Parse an Alembic migration file's module-level metadata.

    Returns None if:
    - The file cannot be read.
    - The file has a Python syntax error.
    - The file has no `revision = "..."` module-level assignment.

    Limitation: merge migrations (where `down_revision = ("rev_a", "rev_b")`)
    are treated as unparseable — the tuple fails the string-literal check in
    `_literal_string_or_none`. A future task may add merge-node support;
    until then, these are warned and skipped.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning(
            "alembic_migration_syntax_error",
            file=str(path),
            line=exc.lineno,
            error=str(exc.msg),
        )
        return None

    revision: str | None = None
    down_revision: str | None = None
    upgrade_ops: list[dict[str, str]] = []
    downgrade_ops: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target_name = node.targets[0].id
            if target_name == "revision":
                revision = _literal_string_or_none(node.value)
            elif target_name == "down_revision":
                down_revision = _literal_string_or_none(node.value)
        elif isinstance(node, ast.FunctionDef):
            if node.name == "upgrade":
                upgrade_ops = extract_ops_from_function(node)
            elif node.name == "downgrade":
                downgrade_ops = extract_ops_from_function(node)

    if revision is None:
        return None

    return MigrationInfo(
        file_path=path,
        revision_id=revision,
        down_revision=down_revision,
        upgrade_ops=upgrade_ops,
        downgrade_ops=downgrade_ops,
    )


def _literal_string_or_none(value: ast.expr) -> str | None:
    """Return the string literal value, or None for `None`/non-literal exprs."""
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str):
            return value.value
        if value.value is None:
            return None
    return None


_SINGLE_TARGET_OPS = frozenset({"create_table", "drop_table"})
_TABLE_COLUMN_OPS = frozenset({"add_column", "drop_column"})
# alter_column / rename_table captured with target only — full modeling is M3+.
_OTHER_TABLE_OPS = frozenset({"alter_column", "rename_table"})


def _walk_excluding_nested_scopes(node: ast.AST) -> Iterator[ast.AST]:
    """Like ast.walk but does not descend into nested function/lambda bodies.

    Alembic migrations almost never use nested defs, but if they do the
    inner function's ops belong to that helper, not to upgrade/downgrade.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _walk_excluding_nested_scopes(child)


def extract_ops_from_function(func: ast.FunctionDef) -> list[dict[str, str]]:
    """Scan a function body for `op.<known_name>(...)` calls.

    Returns a list of summary dicts — one per recognized op call — preserving
    source order. Unknown ops (e.g. `op.execute`, `op.bulk_insert`) are
    silently skipped rather than raised, so an unfamiliar Alembic pattern in
    one file doesn't hide the rest of the migration.
    """
    ops: list[dict[str, str]] = []
    for stmt in _walk_excluding_nested_scopes(func):
        if not isinstance(stmt, ast.Call):
            continue
        func_expr = stmt.func
        if not (
            isinstance(func_expr, ast.Attribute)
            and isinstance(func_expr.value, ast.Name)
            and func_expr.value.id == "op"
        ):
            continue
        op_name = func_expr.attr
        if op_name in _SINGLE_TARGET_OPS:
            target = _first_string_arg(stmt.args)
            if target is not None:
                ops.append({"op": op_name, "target": target})
        elif op_name in _TABLE_COLUMN_OPS:
            table = _first_string_arg(stmt.args)
            if table is None:
                continue
            # Alembic: add_column(table, sa.Column("name", ...))
            #          drop_column(table, "name")
            column = _second_string_arg(stmt.args)
            if column is None:
                column = _column_name_from_sa_column(stmt.args)
            if column is not None:
                ops.append({"op": op_name, "target": table, "column": column})
        elif op_name in _OTHER_TABLE_OPS:
            target = _first_string_arg(stmt.args)
            if target is not None:
                ops.append({"op": op_name, "target": target})
    return ops


def _first_string_arg(args: list[ast.expr]) -> str | None:
    if not args:
        return None
    first = args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _second_string_arg(args: list[ast.expr]) -> str | None:
    if len(args) < 2:
        return None
    second = args[1]
    if isinstance(second, ast.Constant) and isinstance(second.value, str):
        return second.value
    return None


def _column_name_from_sa_column(args: list[ast.expr]) -> str | None:
    """Extract the column name from a `sa.Column("name", ...)` arg."""
    if len(args) < 2:
        return None
    second = args[1]
    if not isinstance(second, ast.Call):
        return None
    func_expr = second.func
    # Accept both `sa.Column(...)` and `Column(...)`.
    is_sa_column = isinstance(func_expr, ast.Attribute) and func_expr.attr == "Column"
    is_bare_column = isinstance(func_expr, ast.Name) and func_expr.id == "Column"
    if not (is_sa_column or is_bare_column):
        return None
    return _first_string_arg(second.args)


class AlembicPlugin(FrameworkPlugin):
    name = "alembic"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is None:
            return PluginDetectionResult.not_detected()

        root = context.manifest.root_path
        ini = root / "alembic.ini"
        if ini.is_file():
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason="alembic.ini present at project root",
            )

        env_py = root / "migrations" / "env.py"
        if env_py.is_file():
            try:
                text = env_py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return PluginDetectionResult.not_detected()
            if "from alembic import" in text or "import alembic" in text:
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="migrations/env.py imports alembic",
                )
            logger.debug(
                "alembic_detect_env_py_no_import",
                env_py=str(env_py),
            )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("alembic_extract_start")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        if context.manifest is None:
            log.warning("alembic_extract_no_manifest")
            return PluginResult(
                nodes=nodes,
                edges=edges,
                layer_assignments={},
                entry_points=[],
                warnings=warnings,
            )

        versions_dir = self._find_versions_dir(context.manifest.root_path)
        if versions_dir is None:
            log.info("alembic_no_versions_dir")
            return PluginResult(
                nodes=nodes,
                edges=edges,
                layer_assignments={},
                entry_points=[],
                warnings=warnings,
            )

        migrations: list[MigrationInfo] = []
        for py_file in sorted(versions_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            info = parse_migration_file(py_file)
            if info is None:
                warnings.append(f"Skipped unparseable migration file: {py_file.name}")
                continue
            migrations.append(info)

        for info in migrations:
            node = GraphNode(
                fqn=f"alembic:{info.revision_id}",
                name=info.revision_id,
                kind=NodeKind.CONFIG_FILE,
                language="python",
                properties={
                    "revision_id": info.revision_id,
                    "down_revision": info.down_revision,
                    "file_path": str(info.file_path),
                    "upgrade_ops": info.upgrade_ops,
                    "downgrade_ops": info.downgrade_ops,
                },
            )
            nodes.append(node)

        known_revisions = {info.revision_id for info in migrations}
        for info in migrations:
            if info.down_revision is None:
                continue
            if info.down_revision not in known_revisions:
                warnings.append(
                    f"Migration {info.revision_id} references unknown parent "
                    f"{info.down_revision}; skipping INHERITS edge"
                )
                continue
            edges.append(
                GraphEdge(
                    source_fqn=f"alembic:{info.revision_id}",
                    target_fqn=f"alembic:{info.down_revision}",
                    kind=EdgeKind.INHERITS,
                    confidence=Confidence.HIGH,
                    evidence="alembic-revision-chain",
                )
            )

        log.info(
            "alembic_extract_complete",
            migrations=len(migrations),
            warnings=len(warnings),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_versions_dir(self, root: Path) -> Path | None:
        """Find the Alembic versions directory relative to project root.

        Alembic defaults put it under `migrations/versions/`; the plan assumes
        that convention. If `alembic.ini` specifies a different `script_location`,
        honor it when possible (the ini file is small enough to scan cheaply).
        """
        default = root / "migrations" / "versions"
        if default.is_dir():
            return default

        ini = root / "alembic.ini"
        if ini.is_file():
            try:
                text = ini.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            for line in text.splitlines():
                stripped = line.strip()
                key, sep, value = stripped.partition("=")
                if sep and key.strip() == "script_location":
                    # Handle inline comments: "script_location = migrations  # prod"
                    script_location = value.split("#", 1)[0].strip()
                    if script_location:
                        candidate = root / script_location / "versions"
                        if candidate.is_dir():
                            return candidate
        return None
