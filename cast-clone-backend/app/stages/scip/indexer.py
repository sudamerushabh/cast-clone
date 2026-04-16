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
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.orchestrator.subprocess_utils import run_subprocess
from app.stages.scip.jdk_detect import resolve_java_home
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
    timeout_seconds: int = 0  # 0 = use global scip_timeout from Settings
    needs_project_name: bool = False
    docker_image: str | None = None


# Language -> SCIP indexer config mapping
SCIP_INDEXER_CONFIGS: dict[str, SCIPIndexerConfig] = {
    "java": SCIPIndexerConfig(
        language="java",
        name="scip-java",
        command_template=["scip-java", "index"],
        docker_image="sourcegraph/scip-java:latest",
    ),
    "typescript": SCIPIndexerConfig(
        language="typescript",
        name="scip-typescript",
        command_template=["npx", "@sourcegraph/scip-typescript", "index"],
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
        needs_project_name=True,
    ),
    "csharp": SCIPIndexerConfig(
        language="csharp",
        name="scip-dotnet",
        command_template=["scip-dotnet", "index"],
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
    build_tool: str | None = None,
) -> list[str]:
    """Build the CLI command for a SCIP indexer.

    Args:
        config: Indexer configuration.
        project_name: Project name (used by scip-python).
        root_path: Project root directory.
        build_tool: Explicit build tool name for scip-java when multiple are detected.

    Returns:
        Command list suitable for subprocess execution.
    """
    cmd = []
    for part in config.command_template:
        cmd.append(part.format(project_name=project_name, root_path=str(root_path)))
    if build_tool and config.name == "scip-java":
        cmd.append(f"--build-tool={build_tool}")
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


# -- Log Scrubbing -----------------------------------------------------------


def _scrub_stderr(s: str, project_root: Path | None) -> str:
    """Best-effort PII scrubbing for subprocess stderr before logging.

    Replaces common sources of PII (absolute project paths, user home
    directories) with stable placeholders so structured log sinks do not
    leak usernames or checkout locations. Not a comprehensive secret
    redactor -- just the minimum to keep routine SCIP output safe.
    """
    if not s:
        return s
    if project_root is not None:
        root_str = str(project_root)
        if root_str:
            s = s.replace(root_str, "<project>")
    try:
        home = os.path.expanduser("~")
    except Exception:
        home = ""
    if home and home not in ("~", ""):
        s = s.replace(home, "<home>")
    return s


# -- Single Indexer Run ------------------------------------------------------


async def _run_scip_in_directory(
    context: AnalysisContext,
    indexer_config: SCIPIndexerConfig,
    project_name: str,
    cwd: Path,
    build_tool: str | None = None,
) -> MergeStats:
    """Run a SCIP indexer in a specific directory and merge results.

    Args:
        context: Pipeline analysis context.
        indexer_config: Configuration for the specific indexer.
        project_name: Project name for command interpolation.
        cwd: Working directory to run the indexer in.
        build_tool: Optional build tool override for scip-java.

    Returns:
        MergeStats from the merger.

    Raises:
        FileNotFoundError: If the SCIP indexer binary is missing from PATH.
        TimeoutError: If the indexer subprocess exceeds its configured timeout.
        RuntimeError: If the indexer subprocess exits with a non-zero code.
    """
    command = build_scip_command(indexer_config, project_name, cwd, build_tool)

    # Auto-detect JDK version for Java projects
    env_overrides: dict[str, str] | None = None
    if indexer_config.language == "java":
        env_overrides = resolve_java_home(cwd)

    logger.info(
        "scip.indexer.start",
        language=indexer_config.language,
        command=" ".join(command),
        cwd=str(cwd),
        java_home=env_overrides.get("JAVA_HOME") if env_overrides else None,
        project_id=context.project_id,
    )

    # Use per-indexer timeout if set, otherwise fall back to global config
    timeout = indexer_config.timeout_seconds
    if timeout <= 0:
        from app.config import get_settings

        timeout = get_settings().scip_timeout

    subprocess_start = time.perf_counter()
    try:
        result = await run_subprocess(
            command=command,
            cwd=cwd,
            timeout=timeout,
            env=env_overrides,
        )
    except FileNotFoundError as err:
        # CHAN-69: SCIP binary missing from PATH -- skip this language so that
        # Stage 4b (LSP fallback) can take over. Non-fatal by design.
        logger.warning(
            "scip.indexer.binary_missing",
            language=indexer_config.language,
            indexer=indexer_config.name,
            binary=command[0] if command else None,
            cwd=str(cwd),
            error=str(err),
            project_id=context.project_id,
            message="SCIP indexer binary not installed; falling back to LSP",
        )
        raise
    except TimeoutError as err:
        # CHAN-70: SCIP indexer hung past its timeout -- surface distinctly
        # from RuntimeError so operators can tune `scip_timeout` or exclude
        # the language.
        elapsed = round(time.perf_counter() - subprocess_start, 3)
        logger.warning(
            "scip.indexer.timeout",
            language=indexer_config.language,
            indexer=indexer_config.name,
            timeout_seconds=timeout,
            elapsed_seconds=elapsed,
            cwd=str(cwd),
            error=str(err),
            project_id=context.project_id,
            message="SCIP indexer timed out; falling back to LSP",
        )
        raise

    # Log stdout/stderr regardless of exit code for observability
    if result.stdout.strip():
        logger.info(
            "scip.indexer.stdout",
            language=indexer_config.language,
            output=result.stdout[:2000],
            project_id=context.project_id,
        )
    project_root = context.manifest.root_path if context.manifest else None
    if result.stderr.strip():
        log_fn = logger.warning if result.returncode != 0 else logger.info
        log_fn(
            "scip.indexer.stderr",
            language=indexer_config.language,
            output=_scrub_stderr(result.stderr[:2000], project_root),
            project_id=context.project_id,
        )

    if result.returncode != 0:
        # CHAN-70: non-zero exit is a RuntimeError, distinct from the timeout
        # path above. Log exit code + stderr for diagnosis.
        scrubbed_stderr = _scrub_stderr(result.stderr[:500], project_root)
        logger.warning(
            "scip.indexer.nonzero_exit",
            language=indexer_config.language,
            indexer=indexer_config.name,
            returncode=result.returncode,
            stderr=scrubbed_stderr,
            cwd=str(cwd),
            project_id=context.project_id,
        )
        raise RuntimeError(
            f"{indexer_config.name} exited with code {result.returncode}: "
            f"{scrubbed_stderr}"
        )

    # Parse the SCIP protobuf output
    index_path = cwd / indexer_config.output_file
    scip_index = parse_scip_index(index_path)

    logger.info(
        "scip.indexer.parsed",
        language=indexer_config.language,
        documents=len(scip_index.documents),
        cwd=str(cwd),
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
        cwd=str(cwd),
        project_id=context.project_id,
    )

    return stats


def _find_subproject_dirs(
    context: AnalysisContext,
    indexer_config: SCIPIndexerConfig,
) -> list[Path]:
    """Find subproject directories that have build tools for this language.

    Uses the build_tools already detected in the manifest during discovery.
    Only returns subproject directories (not the root).

    Args:
        context: Pipeline analysis context with manifest.
        indexer_config: SCIP indexer config (used to match language).

    Returns:
        List of absolute subproject directory paths.
    """
    root_path = context.manifest.root_path
    # Map SCIP language to build tool languages
    lang = indexer_config.language
    # scip-typescript handles both typescript and javascript
    match_languages = {lang}
    if lang == "typescript":
        match_languages.add("javascript")

    # Map build tool names to SCIP indexers
    scip_build_tool_names = {
        "java": {"maven", "gradle"},
        "typescript": {"npm"},
        "python": {"uv/pip", "pip"},
        "csharp": {"dotnet"},
    }
    valid_tool_names = scip_build_tool_names.get(lang, set())

    dirs: list[Path] = []
    for bt in context.manifest.build_tools:
        if bt.subproject_root == ".":
            continue  # skip root — we already tried it
        if bt.language in match_languages and bt.name in valid_tool_names:
            subdir = root_path / bt.subproject_root
            if subdir.is_dir():
                dirs.append(subdir)

    return dirs


async def run_single_scip_indexer(
    context: AnalysisContext,
    indexer_config: SCIPIndexerConfig,
    project_name: str,
) -> MergeStats:
    """Run one SCIP indexer and merge results into context.

    First tries to run at the project root. If that fails, falls back to
    running in each subproject directory that has a matching build tool
    (e.g., per-service pom.xml in a multi-module repo).

    Args:
        context: Pipeline analysis context.
        indexer_config: Configuration for the specific indexer.
        project_name: Project name for command interpolation.

    Returns:
        MergeStats from the merger (aggregated across all subprojects).

    Raises:
        RuntimeError: If all indexer attempts fail.
    """
    root_path = context.manifest.root_path
    indexer_start = time.perf_counter()

    logger.info(
        "scip.indexer.single.start",
        language=indexer_config.language,
        indexer=indexer_config.name,
        root=str(root_path),
        timeout=indexer_config.timeout_seconds,
        project_id=context.project_id,
    )

    # Detect build tool for scip-java when multiple build tools are present
    build_tool: str | None = None
    if indexer_config.name == "scip-java" and context.manifest:
        java_build_tools = [
            bt.name
            for bt in context.manifest.build_tools
            if bt.language == "java"
            and bt.name in ("maven", "gradle")
            and bt.subproject_root == "."
        ]
        if len(java_build_tools) > 1:
            build_tool = "maven" if "maven" in java_build_tools else java_build_tools[0]

    # Check if root has a build file for this language
    root_has_build = any(
        bt.subproject_root == "." and bt.language == indexer_config.language
        for bt in context.manifest.build_tools
    )
    # For typescript, also check javascript
    if indexer_config.language == "typescript" and not root_has_build:
        root_has_build = any(
            bt.subproject_root == "." and bt.language == "javascript"
            for bt in context.manifest.build_tools
        )

    # Try root first if it has a build file
    if root_has_build:
        try:
            return await _run_scip_in_directory(
                context,
                indexer_config,
                project_name,
                root_path,
                build_tool,
            )
        except FileNotFoundError:
            # CHAN-69: If the SCIP binary is missing, trying subprojects won't
            # help -- propagate so the top-level orchestrator routes this
            # language to LSP fallback.
            raise
        except (RuntimeError, TimeoutError) as root_err:
            logger.warning(
                "scip.indexer.root_failed",
                language=indexer_config.language,
                error=str(root_err)[:200],
                error_type=type(root_err).__name__,
                project_id=context.project_id,
            )
            # Fall through to try subprojects

    # Find subproject directories with matching build tools
    sub_dirs = _find_subproject_dirs(context, indexer_config)
    if not sub_dirs:
        if root_has_build:
            raise RuntimeError(
                f"{indexer_config.name} failed at root and no subprojects found"
            )
        raise RuntimeError(f"No build tool found for {indexer_config.language}")

    logger.info(
        "scip.indexer.subprojects",
        language=indexer_config.language,
        count=len(sub_dirs),
        dirs=[d.name for d in sub_dirs],
        project_id=context.project_id,
    )

    # Run SCIP in each subproject in parallel
    tasks = [
        _run_scip_in_directory(
            context,
            indexer_config,
            d.name,
            d,
            build_tool,
        )
        for d in sub_dirs
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    aggregated = MergeStats()
    failures: list[str] = []
    for sub_dir, outcome in zip(sub_dirs, outcomes):
        if isinstance(outcome, FileNotFoundError):
            # CHAN-69: SCIP binary missing -- no subproject can succeed.
            # Propagate so the top-level orchestrator routes this language
            # to LSP fallback instead of masking it as an aggregate
            # RuntimeError.
            logger.warning(
                "scip.indexer.subproject_binary_missing",
                language=indexer_config.language,
                subproject=sub_dir.name,
                project_id=context.project_id,
            )
            raise outcome
        if isinstance(outcome, Exception):
            logger.warning(
                "scip.indexer.subproject_failed",
                language=indexer_config.language,
                subproject=sub_dir.name,
                error=str(outcome)[:200],
                error_type=type(outcome).__name__,
                project_id=context.project_id,
            )
            failures.append(sub_dir.name)
        else:
            aggregated.resolved_count += outcome.resolved_count
            aggregated.new_nodes += outcome.new_nodes
            aggregated.upgraded_edges += outcome.upgraded_edges

    if aggregated.resolved_count == 0 and failures:
        raise RuntimeError(
            f"{indexer_config.name} failed in all subprojects: {failures}"
        )

    if failures:
        context.warnings.append(
            f"SCIP {indexer_config.name} failed in {len(failures)}/{len(sub_dirs)} "
            f"subprojects: {failures}"
        )

    return aggregated


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
    start_time = time.perf_counter()
    logger.info("scip.stage.start", project_id=context.project_id)

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

    elapsed = time.perf_counter() - start_time
    logger.info(
        "scip.stage.complete",
        project_id=context.project_id,
        resolved_count=result.resolved_count,
        languages_resolved=result.languages_resolved,
        languages_failed=result.languages_failed,
        elapsed_seconds=round(elapsed, 3),
    )

    return result
