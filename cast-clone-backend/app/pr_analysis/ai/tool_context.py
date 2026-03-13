from __future__ import annotations

from dataclasses import dataclass

from app.services.neo4j import GraphStore


@dataclass
class ToolContext:
    repo_path: str
    graph_store: GraphStore
    app_name: str
