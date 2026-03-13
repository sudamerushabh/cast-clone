from __future__ import annotations

from dataclasses import dataclass

from app.services.neo4j import GraphStore


@dataclass
class ToolContext:
    repo_path: str            # Source branch path (where PR changes live)
    target_repo_path: str     # Target branch path (for baseline comparison)
    graph_store: GraphStore
    app_name: str
