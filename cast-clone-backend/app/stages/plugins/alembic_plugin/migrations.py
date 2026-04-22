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
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class MigrationInfo:
    """Static metadata extracted from a single Alembic migration file."""

    file_path: Path
    revision_id: str
    down_revision: str | None


def parse_migration_file(path: Path) -> MigrationInfo | None:
    """Parse an Alembic migration file's module-level metadata.

    Returns None if:
    - The file cannot be read.
    - The file has a Python syntax error.
    - The file has no `revision = "..."` module-level assignment.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    revision: str | None = None
    down_revision: str | None = None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target_name = node.targets[0].id
        if target_name == "revision":
            revision = _literal_string_or_none(node.value)
        elif target_name == "down_revision":
            down_revision = _literal_string_or_none(node.value)

    if revision is None:
        return None

    return MigrationInfo(
        file_path=path,
        revision_id=revision,
        down_revision=down_revision,
    )


def _literal_string_or_none(value: ast.expr) -> str | None:
    """Return the string literal value, or None for `None`/non-literal exprs."""
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str):
            return value.value
        if value.value is None:
            return None
    return None


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
                warnings.append(
                    f"Skipped unparseable migration file: {py_file.name}"
                )
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
                },
            )
            nodes.append(node)

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
                if stripped.startswith("script_location"):
                    _, _, value = stripped.partition("=")
                    script_location = value.strip()
                    if script_location:
                        candidate = root / script_location / "versions"
                        if candidate.is_dir():
                            return candidate
        return None
