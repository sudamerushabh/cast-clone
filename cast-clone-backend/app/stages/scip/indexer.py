"""SCIP indexer runner -- Stage 4 of the analysis pipeline.

Detects which SCIP indexers are applicable for the project's languages,
runs them in parallel as async subprocesses, and merges their output into
the SymbolGraph via the merger module.

Each SCIP indexer:
- scip-java: Java, Scala, Kotlin (auto-detects Maven/Gradle)
- scip-typescript: TypeScript and JavaScript
- scip-python: Python (uses Pyright)
- scip-dotnet: C# / .NET

On failure, the language is queued for LSP fallback in Stage 4b.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.orchestrator.subprocess_utils import run_subprocess
from app.stages.scip.merger import MergeStats, merge_scip_into_context
from app.stages.scip.protobuf_parser import parse_scip_index

logger = structlog.get_logger(__name__)


# -- Indexer Configuration ---------------------------------------------------


@dataclass(frozen=True)
class SCIPIndexerConfig:
    """Configuration for a single SCIP indexer."""

    language: str
    name: str
    command_template: list[str]
    output_file: str = "index.scip"
    timeout_seconds: int = 600
    needs_project_name: bool = False
    docker_image: str | None = None


# Language -> SCIP indexer config mapping
SCIP_INDEXER_CONFIGS: dict[str, SCIPIndexerConfig] = {
    "java": SCIPIndexerConfig(
        language="java",
        name="scip-java",
        command_template=["scip-java", "index"],
        timeout_seconds=600,
        docker_image="sourcegraph/scip-java:latest",
    ),
    "typescript": SCIPIndexerConfig(
        language="typescript",
        name="scip-typescript",
        command_template=["npx", "@sourcegraph/scip-typescript", "index"],
        timeout_seconds=600,
    ),
    "python": SCIPIndexerConfig(
        language="python",
        name="scip-python",
        command_template=[
            "scip-python",
            "index",
            ".",
            "--project-name={project_name}",
        ],
        timeout_seconds=600,
        needs_project_name=True,
    ),
    "csharp": SCIPIndexerConfig(
        language="csharp",
        name="scip-dotnet",
        command_template=["scip-dotnet", "index"],
        timeout_seconds=600,
    ),
}

# Map alternative language names to canonical SCIP config keys
_LANGUAGE_ALIASES: dict[str, str] = {
    "javascript": "typescript",  # scip-typescript handles JS too
    "js": "typescript",
    "ts": "typescript",
    "cs": "csharp",
    "c#": "csharp",
    "py": "python",
}


# -- Result Type -------------------------------------------------------------


@dataclass
class SCIPResult:
    """Aggregated result from all SCIP indexer runs."""

    resolved_count: int = 0
    languages_resolved: list[str] = field(default_factory=list)
    languages_failed: list[str] = field(default_factory=list)


# -- Command Building --------------------------------------------------------


def build_scip_command(
    config: SCIPIndexerConfig,
    project_name: str,
    root_path: Path,
) -> list[str]:
    """Build the CLI command for a SCIP indexer.

    Args:
        config: Indexer configuration.
        project_name: Project name (used by scip-python).
        root_path: Project root directory.

    Returns:
        Command list suitable for subprocess execution.
    """
    cmd = []
    for part in config.command_template:
        cmd.append(part.format(project_name=project_name, root_path=str(root_path)))
    return cmd


# -- Indexer Detection -------------------------------------------------------


def detect_available_indexers(
    detected_languages: list[str],
) -> list[SCIPIndexerConfig]:
    """Return SCIP indexer configs for languages that have indexers.

    Args:
        detected_languages: List of language identifiers from project discovery.

    Returns:
        List of applicable SCIPIndexerConfig instances (deduplicated).
    """
    seen: set[str] = set()
    configs: list[SCIPIndexerConfig] = []

    for lang in detected_languages:
        canonical = _LANGUAGE_ALIASES.get(lang.lower(), lang.lower())
        if canonical in SCIP_INDEXER_CONFIGS and canonical not in seen:
            configs.append(SCIP_INDEXER_CONFIGS[canonical])
            seen.add(canonical)

    return configs


# -- Single Indexer Run ------------------------------------------------------


async def run_single_scip_indexer(
    context: AnalysisContext,
    indexer_config: SCIPIndexerConfig,
    project_name: str,
) -> MergeStats:
    """Run one SCIP indexer and merge results into context.

    Args:
        context: Pipeline analysis context.
        indexer_config: Configuration for the specific indexer.
        project_name: Project name for command interpolation.

    Returns:
        MergeStats from the merger.

    Raises:
        RuntimeError: If the indexer subprocess exits with non-zero code.
    """
    root_path = context.manifest.root_path
    command = build_scip_command(indexer_config, project_name, root_path)

    logger.info(
        "scip.indexer.start",
        language=indexer_config.language,
        command=" ".join(command),
        project_id=context.project_id,
    )

    result = await run_subprocess(
        command=command,
        cwd=root_path,
        timeout=indexer_config.timeout_seconds,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{indexer_config.name} exited with code {result.returncode}: "
            f"{result.stderr[:500]}"
        )

    # Parse the SCIP protobuf output
    index_path = root_path / indexer_config.output_file
    scip_index = parse_scip_index(index_path)

    logger.info(
        "scip.indexer.parsed",
        language=indexer_config.language,
        documents=len(scip_index.documents),
        project_id=context.project_id,
    )

    # Merge into context graph
    stats = merge_scip_into_context(context, scip_index, indexer_config.language)

    logger.info(
        "scip.indexer.merged",
        language=indexer_config.language,
        resolved=stats.resolved_count,
        new_nodes=stats.new_nodes,
        upgraded_edges=stats.upgraded_edges,
        project_id=context.project_id,
    )

    return stats


# -- Parallel Indexer Orchestrator -------------------------------------------


async def run_scip_indexers(context: AnalysisContext) -> SCIPResult:
    """Run all applicable SCIP indexers in parallel.

    For each detected language:
    - If a SCIP indexer exists: run it and merge results
    - If no SCIP indexer: add to languages_needing_fallback

    On indexer failure: add to fallback, log warning, continue.

    Args:
        context: Pipeline analysis context (modified in place).

    Returns:
        Aggregated SCIPResult with counts.
    """
    result = SCIPResult()

    if context.manifest is None:
        logger.warning("scip.no_manifest", project_id=context.project_id)
        return result

    detected_langs = [lang.name for lang in context.manifest.detected_languages]
    available_configs = detect_available_indexers(detected_langs)

    # Languages without SCIP indexers go straight to fallback
    covered_languages = {cfg.language for cfg in available_configs}
    # Also include aliased languages as covered
    for lang in detected_langs:
        canonical = _LANGUAGE_ALIASES.get(lang.lower(), lang.lower())
        if canonical not in covered_languages:
            context.languages_needing_fallback.append(lang)

    if not available_configs:
        logger.info("scip.no_indexers", project_id=context.project_id)
        return result

    project_name = context.manifest.root_path.name

    # Run all indexers in parallel
    tasks = [
        run_single_scip_indexer(context, cfg, project_name) for cfg in available_configs
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for cfg, outcome in zip(available_configs, outcomes):
        if isinstance(outcome, Exception):
            logger.warning(
                "scip.indexer.failed",
                language=cfg.language,
                error=str(outcome),
                project_id=context.project_id,
            )
            context.warnings.append(f"SCIP indexer failed for {cfg.name}: {outcome}")
            context.languages_needing_fallback.append(cfg.language)
            result.languages_failed.append(cfg.language)
        else:
            result.resolved_count += outcome.resolved_count
            result.languages_resolved.append(cfg.language)
            context.scip_resolved_languages.add(cfg.language)

    return result
