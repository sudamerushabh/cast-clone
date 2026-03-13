"""Project discovery output: files, languages, frameworks, build tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.enums import Confidence


@dataclass
class SourceFile:
    path: str  # Relative to project root
    language: str
    size_bytes: int


@dataclass
class DetectedLanguage:
    name: str  # "java", "python", "typescript", "csharp"
    file_count: int
    total_loc: int


@dataclass
class DetectedFramework:
    name: str  # "spring-boot", "express", "django", etc.
    language: str
    confidence: Confidence
    evidence: list[str] = field(default_factory=list)


@dataclass
class BuildTool:
    name: str  # "maven", "gradle", "npm", "pip", etc.
    config_file: str  # Relative path to build config
    language: str
    subproject_root: str = "."  # Relative path to subproject dir (default: project root)


@dataclass
class ResolvedDependency:
    name: str
    version: str | None = None
    scope: str = "compile"  # compile, test, runtime, dev


@dataclass
class ResolvedEnvironment:
    """Output of Stage 2 -- dependency resolution."""

    dependencies: dict[str, list[ResolvedDependency]] = field(
        default_factory=dict
    )  # language -> deps
    env_vars: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProjectManifest:
    root_path: Path
    source_files: list[SourceFile] = field(default_factory=list)
    detected_languages: list[DetectedLanguage] = field(default_factory=list)
    detected_frameworks: list[DetectedFramework] = field(default_factory=list)
    build_tools: list[BuildTool] = field(default_factory=list)
    total_files: int = 0
    total_loc: int = 0

    @property
    def language_names(self) -> list[str]:
        return [lang.name for lang in self.detected_languages]

    def has_language(self, name: str) -> bool:
        return name in self.language_names

    def files_for_language(self, language: str) -> list[SourceFile]:
        return [f for f in self.source_files if f.language == language]
