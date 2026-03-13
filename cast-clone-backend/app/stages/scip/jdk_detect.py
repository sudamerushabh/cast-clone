"""Auto-detect required JDK version from build files and find matching installed JDK.

Scans pom.xml / build.gradle for the target Java version, then locates a
matching JDK installation on the system. Returns a JAVA_HOME path that can
be injected into the SCIP subprocess environment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Patterns for extracting Java version from Maven pom.xml
_POM_VERSION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<java\.version>\s*(\d+)\s*</java\.version>"),
    re.compile(r"<maven\.compiler\.source>\s*(\d+)\s*</maven\.compiler\.source>"),
    re.compile(r"<maven\.compiler\.target>\s*(\d+)\s*</maven\.compiler\.target>"),
    re.compile(r"<maven\.compiler\.release>\s*(\d+)\s*</maven\.compiler\.release>"),
    # Handle 1.8 style versions
    re.compile(r"<java\.version>\s*1\.(\d+)\s*</java\.version>"),
    re.compile(r"<maven\.compiler\.source>\s*1\.(\d+)\s*</maven\.compiler\.source>"),
]

# Patterns for extracting Java version from Gradle build files
_GRADLE_VERSION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sourceCompatibility\s*=\s*['\"]?(\d+)['\"]?"),
    re.compile(r"targetCompatibility\s*=\s*['\"]?(\d+)['\"]?"),
    re.compile(r"JavaVersion\.VERSION_(\d+)"),
    re.compile(r"jvmTarget\s*=\s*['\"](\d+)['\"]"),
    # Handle 1.8 style
    re.compile(r"sourceCompatibility\s*=\s*['\"]?1\.(\d+)['\"]?"),
]

# Standard locations where JDKs are installed
_JDK_SEARCH_PATHS: list[Path] = [
    Path("/usr/lib/jvm"),
    Path(os.path.expanduser("~/.sdkman/candidates/java")),
    Path("/usr/local/lib/jvm"),
    Path("/opt/java"),
]


def detect_java_version(project_dir: Path) -> int | None:
    """Detect the target Java version from build files in a directory.

    Checks pom.xml first, then build.gradle / build.gradle.kts.

    Args:
        project_dir: Directory containing build files.

    Returns:
        Major Java version (e.g., 8, 11, 17, 21) or None if not detected.
    """
    # Try pom.xml
    pom = project_dir / "pom.xml"
    if pom.is_file():
        version = _parse_pom_java_version(pom)
        if version is not None:
            return version

    # Try build.gradle / build.gradle.kts
    for gradle_name in ("build.gradle", "build.gradle.kts"):
        gradle = project_dir / gradle_name
        if gradle.is_file():
            version = _parse_gradle_java_version(gradle)
            if version is not None:
                return version

    return None


def _parse_pom_java_version(pom_path: Path) -> int | None:
    """Extract Java version from pom.xml."""
    try:
        content = pom_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    for pattern in _POM_VERSION_PATTERNS:
        match = pattern.search(content)
        if match:
            return int(match.group(1))

    return None


def _parse_gradle_java_version(gradle_path: Path) -> int | None:
    """Extract Java version from build.gradle or build.gradle.kts."""
    try:
        content = gradle_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    for pattern in _GRADLE_VERSION_PATTERNS:
        match = pattern.search(content)
        if match:
            return int(match.group(1))

    return None


def find_installed_jdks() -> dict[int, Path]:
    """Discover installed JDKs and return a map of version -> JAVA_HOME path.

    Scans standard locations for JDK installations.

    Returns:
        Dict mapping major version (e.g., 17) to JAVA_HOME Path.
    """
    jdks: dict[int, Path] = {}

    for search_path in _JDK_SEARCH_PATHS:
        if not search_path.is_dir():
            continue

        for entry in search_path.iterdir():
            if not entry.is_dir():
                continue

            # Check if this looks like a JDK (has bin/java)
            java_bin = entry / "bin" / "java"
            if not java_bin.exists():
                continue

            # Extract version from directory name
            version = _extract_version_from_dirname(entry.name)
            if version is not None and version not in jdks:
                jdks[version] = entry

    return jdks


def _extract_version_from_dirname(name: str) -> int | None:
    """Extract major Java version from a JDK directory name.

    Handles patterns like:
    - java-17-openjdk-amd64
    - java-1.17.0-openjdk-amd64
    - openjdk-21
    - 17.0.2-tem
    - jdk-17
    """
    patterns = [
        re.compile(r"java-(\d+)-"),
        re.compile(r"java-1\.(\d+)\.\d+-"),
        re.compile(r"openjdk-(\d+)"),
        re.compile(r"jdk-?(\d+)"),
        re.compile(r"^(\d+)\.\d+"),
    ]

    for pattern in patterns:
        match = pattern.search(name)
        if match:
            return int(match.group(1))

    return None


def resolve_java_home(project_dir: Path) -> dict[str, str] | None:
    """Detect the project's Java version and return env overrides for JAVA_HOME.

    This is the main entry point for callers. Returns a dict suitable for
    passing to ``run_subprocess(env=...)``.

    Args:
        project_dir: Directory containing the project's build files.

    Returns:
        Dict with JAVA_HOME and PATH overrides, or None if no match needed
        or no matching JDK found.
    """
    required_version = detect_java_version(project_dir)
    if required_version is None:
        logger.debug("jdk_detect.no_version", project_dir=str(project_dir))
        return None

    # Check if current JAVA_HOME already matches
    current_java_home = os.environ.get("JAVA_HOME", "")
    if current_java_home:
        current_version = _extract_version_from_dirname(Path(current_java_home).name)
        if current_version == required_version:
            logger.debug(
                "jdk_detect.current_matches",
                version=required_version,
                java_home=current_java_home,
            )
            return None  # No override needed

    installed = find_installed_jdks()
    jdk_path = installed.get(required_version)

    if jdk_path is None:
        logger.warning(
            "jdk_detect.no_matching_jdk",
            required=required_version,
            available=sorted(installed.keys()),
            project_dir=str(project_dir),
        )
        return None

    java_home = str(jdk_path)
    logger.info(
        "jdk_detect.resolved",
        required_version=required_version,
        java_home=java_home,
        project_dir=str(project_dir),
    )

    # Build PATH with the JDK's bin directory prepended
    current_path = os.environ.get("PATH", "")
    new_path = f"{jdk_path / 'bin'}:{current_path}"

    return {
        "JAVA_HOME": java_home,
        "PATH": new_path,
    }
