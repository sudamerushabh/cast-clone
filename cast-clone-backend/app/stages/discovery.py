"""Stage 1: Project Discovery.

Walks a source directory, identifies languages, build tools, and frameworks.
Produces a ProjectManifest used by all subsequent pipeline stages.

This is a SYNCHRONOUS function -- filesystem I/O is fast and does not benefit
from async. It is the only critical stage (failure = abort pipeline).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import structlog

from app.models.enums import Confidence
from app.models.manifest import (
    BuildTool,
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    SourceFile,
)

logger = structlog.get_logger(__name__)

# -- Constants ────────────────────────────────────────────────────

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".sql": "sql",
}

SKIP_DIRS: set[str] = {
    # Hidden dirs
    ".git",
    ".svn",
    ".hg",
    ".idea",
    ".vscode",
    ".settings",
    ".classpath",
    ".project",
    # Build output
    "node_modules",
    "target",
    "build",
    "dist",
    "bin",
    "obj",
    "__pycache__",
    ".gradle",
    ".mvn",
    # Vendor
    "vendor",
    # Python virtual envs
    ".venv",
    "venv",
    ".tox",
    # .NET
    "packages",
}

# Lines starting with these prefixes (after stripping) are comments
_COMMENT_PREFIXES = ("//", "#", "/*", "*", "*/", "--")


# -- Public API ───────────────────────────────────────────────────


def discover_project(source_path: Path) -> ProjectManifest:
    """Stage 1 entry point: scan filesystem and build a ProjectManifest.

    Args:
        source_path: Absolute path to the root of the codebase to analyze.

    Returns:
        A ProjectManifest with all detected files, languages, frameworks,
        and build tools.

    Raises:
        FileNotFoundError: If source_path does not exist.
        NotADirectoryError: If source_path is not a directory.
    """
    start = time.monotonic()
    log = logger.bind(source_path=str(source_path))
    log.info("discovery.start", stage="discovery")

    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_path}")

    # Step 1: Walk filesystem, detect language per file, count LOC
    source_files = walk_source_files(source_path)

    # Step 2: Aggregate language stats
    lang_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"file_count": 0, "total_loc": 0}
    )
    for sf in source_files:
        lang_stats[sf.language]["file_count"] += 1
        # Count LOC for each file
        full_path = source_path / sf.path
        loc = count_loc(full_path)
        lang_stats[sf.language]["total_loc"] += loc

    detected_languages = [
        DetectedLanguage(
            name=lang_name,
            file_count=stats["file_count"],
            total_loc=stats["total_loc"],
        )
        for lang_name, stats in sorted(
            lang_stats.items(), key=lambda x: x[1]["file_count"], reverse=True
        )
    ]

    total_files = len(source_files)
    total_loc = sum(lang.total_loc for lang in detected_languages)

    # Step 3: Detect build tools
    build_tools = detect_build_tools(source_path)

    # Step 4: Detect frameworks
    detected_frameworks = detect_frameworks(source_path, build_tools)

    manifest = ProjectManifest(
        root_path=source_path,
        source_files=source_files,
        detected_languages=detected_languages,
        detected_frameworks=detected_frameworks,
        build_tools=build_tools,
        total_files=total_files,
        total_loc=total_loc,
    )

    elapsed = time.monotonic() - start
    log.info(
        "discovery.complete",
        stage="discovery",
        total_files=total_files,
        total_loc=total_loc,
        languages=[lang.name for lang in detected_languages],
        frameworks=[f.name for f in detected_frameworks],
        build_tools=[t.name for t in build_tools],
        elapsed_seconds=round(elapsed, 3),
    )

    return manifest


# -- File Walking ─────────────────────────────────────────────────


def walk_source_files(root: Path) -> list[SourceFile]:
    """Recursively walk root, returning SourceFile for each recognized source file.

    Skips hidden directories, build output directories, and vendor directories
    as defined in SKIP_DIRS. Only includes files with extensions in
    EXTENSION_LANGUAGE_MAP.

    Args:
        root: The root directory to walk.

    Returns:
        List of SourceFile with relative paths, detected language, and size.
    """
    source_files: list[SourceFile] = []

    for path in _walk_filtered(root):
        language = detect_language(path)
        if language is not None:
            relative = path.relative_to(root)
            source_files.append(
                SourceFile(
                    path=str(relative),
                    language=language,
                    size_bytes=path.stat().st_size,
                )
            )

    return source_files


def _walk_filtered(root: Path) -> list[Path]:
    """Walk directory tree, skipping SKIP_DIRS. Returns list of file Paths."""
    result: list[Path] = []

    def _recurse(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            logger.warning("discovery.permission_denied", path=str(directory))
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    _recurse(entry)
            elif entry.is_file():
                result.append(entry)

    _recurse(root)
    return result


# -- Language Detection ───────────────────────────────────────────


def detect_language(path: Path) -> str | None:
    """Detect programming language from file extension.

    Args:
        path: Path to a source file (can be relative or absolute).

    Returns:
        Language name string (e.g., "java", "python") or None if unrecognized.
    """
    suffix = path.suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(suffix)


# -- LOC Counting ─────────────────────────────────────────────────


def count_loc(file_path: Path) -> int:
    """Count non-empty, non-comment lines in a source file.

    Simple heuristic: strip whitespace, skip empty lines and lines starting
    with common comment prefixes (//, #, /*, *, --)

    Args:
        file_path: Absolute path to the source file.

    Returns:
        Number of lines of code (LOC). Returns 0 for binary or unreadable files.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return 0

    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT_PREFIXES):
            continue
        count += 1

    return count


# -- Build Tool Detection ─────────────────────────────────────────


def _detect_build_tools_in_dir(
    directory: Path, subproject_root: str = "."
) -> list[BuildTool]:
    """Detect build tools in a single directory.

    Args:
        directory: Directory to scan.
        subproject_root: Relative path from project root to this directory.

    Returns:
        List of detected BuildTool instances.
    """
    tools: list[BuildTool] = []

    # Maven
    if (directory / "pom.xml").is_file():
        tools.append(BuildTool(
            name="maven", config_file="pom.xml",
            language="java", subproject_root=subproject_root,
        ))

    # Gradle
    if (directory / "build.gradle").is_file():
        tools.append(BuildTool(
            name="gradle", config_file="build.gradle",
            language="java", subproject_root=subproject_root,
        ))
    elif (directory / "build.gradle.kts").is_file():
        tools.append(BuildTool(
            name="gradle", config_file="build.gradle.kts",
            language="java", subproject_root=subproject_root,
        ))

    # npm
    if (directory / "package.json").is_file():
        tools.append(BuildTool(
            name="npm", config_file="package.json",
            language="javascript", subproject_root=subproject_root,
        ))

    # Python -- pyproject.toml (uv/pip)
    if (directory / "pyproject.toml").is_file():
        tools.append(BuildTool(
            name="uv/pip", config_file="pyproject.toml",
            language="python", subproject_root=subproject_root,
        ))
    elif (directory / "setup.py").is_file():
        tools.append(BuildTool(
            name="pip", config_file="setup.py",
            language="python", subproject_root=subproject_root,
        ))
    elif (directory / "requirements.txt").is_file():
        tools.append(BuildTool(
            name="pip", config_file="requirements.txt",
            language="python", subproject_root=subproject_root,
        ))

    # .NET -- .csproj or .sln
    csproj_files = list(directory.glob("*.csproj"))
    sln_files = list(directory.glob("*.sln"))
    if csproj_files:
        tools.append(BuildTool(
            name="dotnet", config_file=csproj_files[0].name,
            language="csharp", subproject_root=subproject_root,
        ))
    elif sln_files:
        tools.append(BuildTool(
            name="dotnet", config_file=sln_files[0].name,
            language="csharp", subproject_root=subproject_root,
        ))

    return tools


def detect_build_tools(root: Path) -> list[BuildTool]:
    """Detect build tools at the project root and in immediate subdirectories.

    For monorepos and multi-service projects, each subdirectory may contain
    its own build configuration (pom.xml, package.json, etc.). We scan one
    level deep to discover these subprojects.

    Args:
        root: The root directory of the project.

    Returns:
        List of detected BuildTool instances with subproject_root set.
    """
    # Scan root directory
    tools = _detect_build_tools_in_dir(root, subproject_root=".")

    # Scan immediate subdirectories for additional build tools
    root_languages = {t.language for t in tools}
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        sub_tools = _detect_build_tools_in_dir(child, subproject_root=child.name)
        for st in sub_tools:
            # Always add subproject tools — they represent independent build units
            # even if the same language exists at root (e.g., root pom + child poms)
            tools.append(st)

    return tools


# -- Framework Detection ──────────────────────────────────────────


def detect_frameworks(
    root: Path, build_tools: list[BuildTool]
) -> list[DetectedFramework]:
    """Detect frameworks by scanning build configuration files for known dependencies.

    Args:
        root: The root directory of the project.
        build_tools: Previously detected build tools (from detect_build_tools).

    Returns:
        List of detected frameworks with confidence levels and evidence.
    """
    frameworks: list[DetectedFramework] = []

    for tool in build_tools:
        config_path = root / tool.subproject_root / tool.config_file
        if not config_path.is_file():
            continue

        if tool.name == "maven":
            frameworks.extend(_detect_frameworks_maven(config_path))
        elif tool.name == "gradle":
            frameworks.extend(_detect_frameworks_gradle(config_path))
        elif tool.name == "npm":
            frameworks.extend(_detect_frameworks_npm(config_path))
        elif tool.name in ("uv/pip", "pip"):
            frameworks.extend(_detect_frameworks_python(config_path, tool.config_file))
        elif tool.name == "dotnet":
            frameworks.extend(_detect_frameworks_dotnet(config_path))

    return frameworks


def _detect_frameworks_maven(pom_path: Path) -> list[DetectedFramework]:
    """Detect Java frameworks from pom.xml."""
    frameworks: list[DetectedFramework] = []

    try:
        content = pom_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    # Spring Boot
    if "spring-boot" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot dependency"],
            )
        )

    # Hibernate
    if "hibernate" in content.lower():
        frameworks.append(
            DetectedFramework(
                name="hibernate",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains hibernate dependency"],
            )
        )

    # Spring Data JPA
    if "spring-data-jpa" in content or "spring-boot-starter-data-jpa" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-data-jpa",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-data-jpa dependency"],
            )
        )

    return frameworks


def _detect_frameworks_gradle(gradle_path: Path) -> list[DetectedFramework]:
    """Detect Java frameworks from build.gradle or build.gradle.kts."""
    frameworks: list[DetectedFramework] = []

    try:
        content = gradle_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    if "spring-boot" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains spring-boot"],
            )
        )

    if "hibernate" in content.lower():
        frameworks.append(
            DetectedFramework(
                name="hibernate",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains hibernate"],
            )
        )

    if "spring-data-jpa" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-data-jpa",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains spring-data-jpa"],
            )
        )

    return frameworks


def _detect_frameworks_npm(package_json_path: Path) -> list[DetectedFramework]:
    """Detect JS/TS frameworks from package.json."""
    frameworks: list[DetectedFramework] = []

    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frameworks

    all_deps: dict[str, str] = {}
    all_deps.update(data.get("dependencies", {}))
    all_deps.update(data.get("devDependencies", {}))

    # Express
    if "express" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="express",
                language="javascript",
                confidence=Confidence.HIGH,
                evidence=["package.json has express dependency"],
            )
        )

    # React
    if "react" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="react",
                language="javascript",
                confidence=Confidence.HIGH,
                evidence=["package.json has react dependency"],
            )
        )

    # NestJS
    if "@nestjs/core" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="nestjs",
                language="typescript",
                confidence=Confidence.HIGH,
                evidence=["package.json has @nestjs/core dependency"],
            )
        )

    # Angular
    if "@angular/core" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="angular",
                language="typescript",
                confidence=Confidence.HIGH,
                evidence=["package.json has @angular/core dependency"],
            )
        )

    return frameworks


def _detect_frameworks_python(
    config_path: Path, config_file: str
) -> list[DetectedFramework]:
    """Detect Python frameworks from pyproject.toml or requirements.txt."""
    frameworks: list[DetectedFramework] = []

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    content_lower = content.lower()

    # Django
    if "django" in content_lower:
        # Avoid false positive on django-rest-framework matching without django
        # "django" will match "django==5.0", "Django>=4.0", etc.
        frameworks.append(
            DetectedFramework(
                name="django",
                language="python",
                confidence=Confidence.HIGH,
                evidence=[f"{config_file} contains django dependency"],
            )
        )

    # FastAPI
    if "fastapi" in content_lower:
        frameworks.append(
            DetectedFramework(
                name="fastapi",
                language="python",
                confidence=Confidence.HIGH,
                evidence=[f"{config_file} contains fastapi dependency"],
            )
        )

    return frameworks


def _detect_frameworks_dotnet(config_path: Path) -> list[DetectedFramework]:
    """Detect .NET frameworks from .csproj or .sln files.

    For .sln files, scans all .csproj files under the same directory tree
    since .sln files themselves don't contain package/SDK references.
    For .csproj files, checks the file directly.
    """
    frameworks: list[DetectedFramework] = []

    # Collect .csproj files to check
    csproj_files: list[Path] = []
    if config_path.suffix == ".sln":
        # .sln files don't contain framework references — scan all .csproj
        # files under the project root for ASP.NET / EF markers.
        csproj_files = list(config_path.parent.rglob("*.csproj"))
    else:
        csproj_files = [config_path]

    aspnet_found = False
    ef_found = False

    for csproj_path in csproj_files:
        try:
            content = csproj_path.read_text(encoding="utf-8")
        except OSError:
            continue

        if not aspnet_found and (
            "Microsoft.AspNetCore" in content
            or 'Sdk="Microsoft.NET.Sdk.Web"' in content
        ):
            frameworks.append(
                DetectedFramework(
                    name="aspnet",
                    language="csharp",
                    confidence=Confidence.HIGH,
                    evidence=[
                        f"{csproj_path.name} contains ASP.NET Core reference"
                    ],
                )
            )
            aspnet_found = True

        if not ef_found and (
            "Microsoft.EntityFrameworkCore" in content
            or "EntityFramework" in content
        ):
            frameworks.append(
                DetectedFramework(
                    name="efcore",
                    language="csharp",
                    confidence=Confidence.HIGH,
                    evidence=[
                        f"{csproj_path.name} contains Entity Framework reference"
                    ],
                )
            )
            ef_found = True

        if aspnet_found and ef_found:
            break

    return frameworks
