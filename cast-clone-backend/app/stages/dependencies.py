"""Stage 2: Dependency Resolution.

Parses build configuration files (pom.xml, package.json, pyproject.toml,
requirements.txt, .csproj) to extract declared dependencies. For Phase 1,
we only parse declaration files -- we do NOT run build tools (mvn, npm, etc.).

This is ASYNC to future-proof for subprocess-based resolution in later phases.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import structlog

from app.models.manifest import (
    BuildTool,
    ProjectManifest,
    ResolvedDependency,
    ResolvedEnvironment,
)

logger = structlog.get_logger(__name__)

# Maven POM namespace
_MVN_NS = {"mvn": "http://maven.apache.org/POM/4.0.0"}


# -- Public API ───────────────────────────────────────────────────


async def resolve_dependencies(
    manifest: ProjectManifest,
) -> ResolvedEnvironment:
    """Stage 2 entry point: parse build files and optionally build a Python venv.

    For Phase 1, dependency declaration parsing does NOT run build tools (mvn
    dependency:tree, npm install). It only parses the declaration files. The
    one exception is Python: if the project declares Python dependencies, we
    build a sandboxed venv via `uv` so that Stage 4 `scip-python` has a
    populated site-packages to resolve imports against.

    Args:
        manifest: The ProjectManifest produced by Stage 1.

    Returns:
        ResolvedEnvironment with dependencies, optional python_venv_path.
    """
    start = time.monotonic()
    log = logger.bind(project_root=str(manifest.root_path))
    log.info("dependencies.start", stage="dependencies")

    dependencies: dict[str, list[ResolvedDependency]] = {}
    errors: list[str] = []

    for tool in manifest.build_tools:
        config_path = manifest.root_path / tool.config_file
        language = tool.language

        try:
            deps = _parse_for_tool(tool, config_path)
            if deps:
                existing = dependencies.get(language, [])
                existing.extend(deps)
                dependencies[language] = existing
        except Exception as e:
            msg = f"Failed to parse {tool.config_file} ({tool.name}): {e}"
            log.warning("dependencies.parse_error", error=msg)
            errors.append(msg)

    # Build Python venv for SCIP Python indexer (M1)
    python_venv_path: Path | None = None
    has_python = any(tool.language == "python" for tool in manifest.build_tools)
    if has_python:
        python_venv_path = build_python_venv(manifest.root_path)
        if python_venv_path is None:
            errors.append(
                "Python venv build failed; SCIP will run against system Python"
            )
        else:
            log.info("dependencies.venv_ready", path=str(python_venv_path))

    elapsed = time.monotonic() - start
    dep_counts = {lang: len(deps) for lang, deps in dependencies.items()}
    log.info(
        "dependencies.complete",
        stage="dependencies",
        dependency_counts=dep_counts,
        error_count=len(errors),
        elapsed_seconds=round(elapsed, 3),
    )

    return ResolvedEnvironment(
        dependencies=dependencies,
        env_vars={},
        errors=errors,
        python_venv_path=python_venv_path,
    )


# -- Dispatch ─────────────────────────────────────────────────────


def _parse_for_tool(tool: BuildTool, config_path: Path) -> list[ResolvedDependency]:
    """Route to the correct parser based on build tool type."""
    if tool.name == "maven":
        return parse_maven_dependencies(config_path)
    elif tool.name == "gradle":
        return _parse_gradle_dependencies(config_path)
    elif tool.name == "npm":
        return parse_npm_dependencies(config_path)
    elif tool.name in ("uv/pip", "pip"):
        return parse_python_dependencies(config_path)
    elif tool.name == "dotnet":
        return parse_dotnet_dependencies(config_path)
    return []


# -- Maven ────────────────────────────────────────────────────────


def parse_maven_dependencies(pom_path: Path) -> list[ResolvedDependency]:
    """Parse Maven pom.xml and extract <dependency> elements.

    Extracts groupId:artifactId as the name, version (may be None if managed
    by parent POM), and scope (defaults to "compile").

    Args:
        pom_path: Path to pom.xml.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not pom_path.is_file():
        return []

    try:
        tree = ET.parse(pom_path)  # noqa: S314
    except ET.ParseError:
        logger.warning("dependencies.maven_parse_error", path=str(pom_path))
        return []

    root = tree.getroot()
    deps: list[ResolvedDependency] = []

    # Handle both namespaced and non-namespaced POM files
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    for dep_elem in root.iter(f"{ns}dependency"):
        group_id_elem = dep_elem.find(f"{ns}groupId")
        artifact_id_elem = dep_elem.find(f"{ns}artifactId")

        if group_id_elem is None or artifact_id_elem is None:
            continue

        group_id = group_id_elem.text or ""
        artifact_id = artifact_id_elem.text or ""
        name = f"{group_id}:{artifact_id}"

        version_elem = dep_elem.find(f"{ns}version")
        version = version_elem.text if version_elem is not None else None

        scope_elem = dep_elem.find(f"{ns}scope")
        scope = scope_elem.text if scope_elem is not None else "compile"

        deps.append(ResolvedDependency(name=name, version=version, scope=scope))

    return deps


# -- Gradle ───────────────────────────────────────────────────────


def _parse_gradle_dependencies(gradle_path: Path) -> list[ResolvedDependency]:
    """Parse Gradle build file with regex heuristics.

    Gradle build files are Groovy/Kotlin DSL, not structured data. We use
    regex to extract the most common dependency declaration patterns.
    This is a best-effort parser.

    Args:
        gradle_path: Path to build.gradle or build.gradle.kts.

    Returns:
        List of ResolvedDependency extracted via regex.
    """
    if not gradle_path.is_file():
        return []

    try:
        content = gradle_path.read_text(encoding="utf-8")
    except OSError:
        return []

    deps: list[ResolvedDependency] = []

    # Match patterns like: implementation 'group:artifact:version'
    # or: implementation("group:artifact:version")
    pattern = re.compile(
        r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|"""
        r"""testRuntimeOnly|annotationProcessor)\s*"""
        r"""[\('"]+([^:'"]+):([^:'"]+)(?::([^'")\s]+))?['")\s]""",
        re.MULTILINE,
    )

    for match in pattern.finditer(content):
        group_id = match.group(1).strip()
        artifact_id = match.group(2).strip()
        version = match.group(3).strip() if match.group(3) else None
        name = f"{group_id}:{artifact_id}"

        # Determine scope from configuration name
        line = content[max(0, match.start() - 50) : match.start() + 5]
        scope = "compile"
        if "testImplementation" in line or "testRuntimeOnly" in line:
            scope = "test"
        elif "runtimeOnly" in line:
            scope = "runtime"
        elif "compileOnly" in line:
            scope = "compile"

        deps.append(ResolvedDependency(name=name, version=version, scope=scope))

    return deps


# -- npm ──────────────────────────────────────────────────────────


def parse_npm_dependencies(package_json_path: Path) -> list[ResolvedDependency]:
    """Parse package.json and extract dependencies + devDependencies.

    Args:
        package_json_path: Path to package.json.

    Returns:
        List of ResolvedDependency. Production deps get scope "compile",
        dev deps get scope "dev". Empty list on any parse error.
    """
    if not package_json_path.is_file():
        return []

    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("dependencies.npm_parse_error", path=str(package_json_path))
        return []

    deps: list[ResolvedDependency] = []

    for name, version in data.get("dependencies", {}).items():
        deps.append(ResolvedDependency(name=name, version=version, scope="compile"))

    for name, version in data.get("devDependencies", {}).items():
        deps.append(ResolvedDependency(name=name, version=version, scope="dev"))

    return deps


# -- Python ───────────────────────────────────────────────────────


# Regex to split a PEP 508 dependency specifier into name and version
_PEP508_PATTERN = re.compile(
    r"^([a-zA-Z0-9][-a-zA-Z0-9_.]*)"  # package name
    r"(?:\[[-a-zA-Z0-9_.,\s]*\])?"  # optional extras like [standard]
    r"(.*)$"  # version specifier remainder
)


def parse_python_dependencies(
    config_path: Path,
) -> list[ResolvedDependency]:
    """Parse Python dependency files (requirements.txt or pyproject.toml).

    For requirements.txt: parses each line as a PEP 508 dependency.
    For pyproject.toml: extracts [project].dependencies array.

    Args:
        config_path: Path to requirements.txt or pyproject.toml.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not config_path.is_file():
        return []

    if config_path.name == "pyproject.toml":
        return _parse_pyproject_toml(config_path)
    else:
        return _parse_requirements_txt(config_path)


def _parse_requirements_txt(req_path: Path) -> list[ResolvedDependency]:
    """Parse requirements.txt format."""
    try:
        content = req_path.read_text(encoding="utf-8")
    except OSError:
        return []

    deps: list[ResolvedDependency] = []

    for line in content.splitlines():
        line = line.strip()

        # Skip empty lines, comments, and options
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        dep = _parse_pep508_line(line)
        if dep is not None:
            deps.append(dep)

    return deps


def _parse_pyproject_toml(toml_path: Path) -> list[ResolvedDependency]:
    """Parse pyproject.toml [project].dependencies array."""
    try:
        import tomllib
    except ImportError:
        # Python < 3.11 fallback (should not happen with 3.12)
        return []

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning("dependencies.pyproject_parse_error", path=str(toml_path))
        return []

    deps: list[ResolvedDependency] = []
    dep_strings = data.get("project", {}).get("dependencies", [])

    for dep_str in dep_strings:
        dep = _parse_pep508_line(dep_str.strip())
        if dep is not None:
            deps.append(dep)

    return deps


def _parse_pep508_line(line: str) -> ResolvedDependency | None:
    """Parse a single PEP 508 dependency specifier line.

    Examples:
        "flask==3.0.0" -> ResolvedDependency(name="flask", version="3.0.0")
        "requests>=2.31.0" -> ResolvedDependency(name="requests", version=">=2.31.0")
        "numpy" -> ResolvedDependency(name="numpy", version=None)
        "uvicorn[standard]>=0.24.0" ->
            ResolvedDependency(name="uvicorn", version=">=0.24.0")

    Args:
        line: A single dependency specifier string.

    Returns:
        ResolvedDependency or None if the line cannot be parsed.
    """
    match = _PEP508_PATTERN.match(line)
    if not match:
        return None

    name = match.group(1).strip()
    version_part = match.group(2).strip()

    # Clean up version: "==3.0.0" -> "3.0.0", ">=2.31.0" -> ">=2.31.0"
    version: str | None = None
    if version_part:
        if version_part.startswith("=="):
            version = version_part[2:].strip()
        elif version_part:
            version = version_part.strip()

    return ResolvedDependency(name=name, version=version, scope="compile")


# -- .NET ─────────────────────────────────────────────────────────


def parse_dotnet_dependencies(csproj_path: Path) -> list[ResolvedDependency]:
    """Parse .csproj XML and extract <PackageReference> elements.

    Args:
        csproj_path: Path to a .csproj file.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not csproj_path.is_file():
        return []

    try:
        tree = ET.parse(csproj_path)  # noqa: S314
    except ET.ParseError:
        logger.warning("dependencies.dotnet_parse_error", path=str(csproj_path))
        return []

    root = tree.getroot()
    deps: list[ResolvedDependency] = []

    # .csproj files may or may not have a namespace
    for pkg_ref in root.iter("PackageReference"):
        name = pkg_ref.get("Include")
        if not name:
            continue
        version = pkg_ref.get("Version")

        deps.append(ResolvedDependency(name=name, version=version, scope="compile"))

    return deps


# -- Python venv builder (Stage 2, M1) ─────────────────────────────

# Default timeout in seconds for `uv pip install`. Covers mid-size repos.
_UV_INSTALL_TIMEOUT_SECONDS = 300


def build_python_venv(project_root: Path) -> Path | None:
    """Create a sandboxed venv and install the project's Python dependencies.

    Uses `uv venv` + `uv pip install` (falls back from `-e .` to `-r requirements.txt`).

    Fail-open contract: any failure returns None and must be surfaced via the
    caller's warnings list — never raises.

    Args:
        project_root: Absolute path to the project root directory.

    Returns:
        Absolute path to the venv directory on success, else None.
    """
    # Skip projects with no Python build file
    has_pyproject = (project_root / "pyproject.toml").is_file()
    has_requirements = (project_root / "requirements.txt").is_file()
    has_setup = (project_root / "setup.py").is_file()
    if not (has_pyproject or has_requirements or has_setup):
        return None

    # Stable per-project venv directory under TMPDIR
    venv_dir = (
        Path(tempfile.gettempdir()) / f"cast-venv-{project_root.name}-{os.getpid()}"
    )

    try:
        # 1. Create the venv
        subprocess.run(
            ["uv", "venv", str(venv_dir)],
            cwd=project_root,
            timeout=60,
            capture_output=True,
            text=True,
            check=True,
        )
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ) as e:
        logger.warning(
            "venv.create_failed",
            project=str(project_root),
            error=str(e)[:200],
        )
        return None

    # 2. Install dependencies: -e . first, fall back to requirements.txt
    install_env = {
        **os.environ,
        "VIRTUAL_ENV": str(venv_dir),
        "PATH": f"{venv_dir}/bin:{os.environ.get('PATH', '')}",
    }
    install_ok = False

    if has_pyproject or has_setup:
        try:
            subprocess.run(
                ["uv", "pip", "install", "-e", "."],
                cwd=project_root,
                timeout=_UV_INSTALL_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                check=True,
                env=install_env,
            )
            install_ok = True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            logger.warning(
                "venv.install_editable_failed",
                project=str(project_root),
                error=str(e)[:200],
            )

    if not install_ok and has_requirements:
        try:
            subprocess.run(
                ["uv", "pip", "install", "-r", "requirements.txt"],
                cwd=project_root,
                timeout=_UV_INSTALL_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                check=True,
                env=install_env,
            )
            install_ok = True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            logger.warning(
                "venv.install_requirements_failed",
                project=str(project_root),
                error=str(e)[:200],
            )

    # Partial-install success is still success: scip-python can use whatever
    # got installed. Only return None if BOTH install paths failed.
    if not install_ok:
        logger.warning("venv.install_all_failed", project=str(project_root))
        # Keep the venv anyway — even empty it gives scip-python
        # the right Python interpreter
    return venv_dir
