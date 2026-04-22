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

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


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

        # Task 9 populates nodes; Task 10 populates per-revision op lists;
        # Task 11 adds INHERITS edges.

        log.info(
            "alembic_extract_complete",
            nodes=len(nodes),
            edges=len(edges),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )
