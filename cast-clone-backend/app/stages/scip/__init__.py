"""SCIP indexer integration -- Stage 4 of the analysis pipeline.

Runs language-specific SCIP indexers as subprocesses, parses the resulting
Protobuf index files, and merges compiler-accurate symbol data into the
SymbolGraph built by tree-sitter in Stage 3.
"""

from app.stages.scip.indexer import run_scip_indexers
from app.stages.scip.merger import merge_scip_into_context

__all__ = ["run_scip_indexers", "merge_scip_into_context"]
