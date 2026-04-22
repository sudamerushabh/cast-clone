"""Tests for Stage 2: Dependency Resolution."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.manifest import (
    BuildTool,
    ProjectManifest,
    ResolvedDependency,
    ResolvedEnvironment,
)
from app.stages.dependencies import (
    build_python_venv,
    parse_maven_dependencies,
    parse_npm_dependencies,
    parse_python_dependencies,
    parse_dotnet_dependencies,
    resolve_dependencies,
)


# -- Maven Dependency Parsing ─────────────────────────────────────


class TestParseMavenDependencies:
    def test_extracts_dependencies(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        assert len(deps) > 0

    def test_extracts_group_and_artifact(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        dep_names = [d.name for d in deps]
        assert "org.springframework.boot:spring-boot-starter-web" in dep_names

    def test_extracts_version_when_present(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        hibernate = [d for d in deps if "hibernate" in d.name]
        assert len(hibernate) == 1
        assert hibernate[0].version == "6.4.0.Final"

    def test_version_is_none_when_managed(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        starter_web = [d for d in deps if "starter-web" in d.name]
        assert len(starter_web) == 1
        assert starter_web[0].version is None

    def test_extracts_scope(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        h2 = [d for d in deps if "h2" in d.name]
        assert len(h2) == 1
        assert h2[0].scope == "runtime"

    def test_default_scope_is_compile(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        starter_web = [d for d in deps if "starter-web" in d.name]
        assert starter_web[0].scope == "compile"

    def test_test_scope(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        test_deps = [d for d in deps if d.scope == "test"]
        assert len(test_deps) >= 1

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_maven_dependencies(tmp_path / "nonexistent.xml")
        assert deps == []

    def test_malformed_xml_returns_empty(self, tmp_path: Path):
        bad = tmp_path / "pom.xml"
        bad.write_text("this is not xml")
        deps = parse_maven_dependencies(bad)
        assert deps == []


# -- npm Dependency Parsing ───────────────────────────────────────


class TestParseNpmDependencies:
    def test_extracts_dependencies(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        assert len(deps) > 0

    def test_extracts_name_and_version(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        express = [d for d in deps if d.name == "express"]
        assert len(express) == 1
        assert express[0].version == "^4.18.2"

    def test_includes_dev_dependencies(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        dev_deps = [d for d in deps if d.scope == "dev"]
        assert len(dev_deps) >= 1
        assert any(d.name == "jest" for d in dev_deps)

    def test_production_scope_for_deps(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        express = [d for d in deps if d.name == "express"]
        assert express[0].scope == "compile"

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_npm_dependencies(tmp_path / "nope.json")
        assert deps == []

    def test_malformed_json_returns_empty(self, tmp_path: Path):
        bad = tmp_path / "package.json"
        bad.write_text("{invalid json")
        deps = parse_npm_dependencies(bad)
        assert deps == []


# -- Python Dependency Parsing ────────────────────────────────────


class TestParsePythonDependencies:
    def test_parses_requirements_txt(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask==3.0.0\nrequests>=2.31.0\nnumpy\n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 3

    def test_extracts_version_from_requirements(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask==3.0.0\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "flask"
        assert deps[0].version == "3.0.0"

    def test_extracts_version_with_gte(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31.0\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "requests"
        assert deps[0].version == ">=2.31.0"

    def test_no_version_gives_none(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "numpy"
        assert deps[0].version is None

    def test_skips_comments_and_blanks(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("# comment\n\nflask==3.0.0\n  \n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 1

    def test_skips_option_lines(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("-r other.txt\n--index-url https://pypi.org\nflask\n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 1

    def test_parses_pyproject_toml(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "myapp"\ndependencies = [\n'
            '    "fastapi>=0.104.0",\n'
            '    "uvicorn[standard]",\n'
            '    "pydantic>=2.0",\n'
            "]\n"
        )
        deps = parse_python_dependencies(toml)
        assert len(deps) == 3
        fastapi = [d for d in deps if d.name == "fastapi"]
        assert len(fastapi) == 1
        assert fastapi[0].version == ">=0.104.0"

    def test_pyproject_with_extras_strips_extras(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "x"\ndependencies = ["uvicorn[standard]>=0.24.0"]\n'
        )
        deps = parse_python_dependencies(toml)
        assert deps[0].name == "uvicorn"

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_python_dependencies(tmp_path / "nope.txt")
        assert deps == []


# -- .NET Dependency Parsing ──────────────────────────────────────


class TestParseDotnetDependencies:
    def test_extracts_package_references(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />\n'
            '    <PackageReference Include="Serilog" Version="3.1.1" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        deps = parse_dotnet_dependencies(csproj)
        assert len(deps) == 2
        json_dep = [d for d in deps if d.name == "Newtonsoft.Json"]
        assert len(json_dep) == 1
        assert json_dep[0].version == "13.0.3"

    def test_handles_no_version_attribute(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="SomePackage" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        deps = parse_dotnet_dependencies(csproj)
        assert len(deps) == 1
        assert deps[0].version is None

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_dotnet_dependencies(tmp_path / "nope.csproj")
        assert deps == []


# -- Full Resolve Dependencies Integration ────────────────────────


class TestResolveDependencies:
    @pytest.mark.asyncio
    async def test_resolves_maven_project(self, raw_java_dir: Path):
        manifest = ProjectManifest(
            root_path=raw_java_dir,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java")
            ],
        )
        env = await resolve_dependencies(manifest)
        assert isinstance(env, ResolvedEnvironment)
        assert "java" in env.dependencies
        assert len(env.dependencies["java"]) > 0

    @pytest.mark.asyncio
    async def test_resolves_npm_project(self, express_app_dir: Path):
        manifest = ProjectManifest(
            root_path=express_app_dir,
            build_tools=[
                BuildTool(
                    name="npm",
                    config_file="package.json",
                    language="javascript",
                )
            ],
        )
        env = await resolve_dependencies(manifest)
        assert "javascript" in env.dependencies
        assert any(d.name == "express" for d in env.dependencies["javascript"])

    @pytest.mark.asyncio
    async def test_empty_manifest_returns_empty_env(self, tmp_path: Path):
        manifest = ProjectManifest(root_path=tmp_path)
        env = await resolve_dependencies(manifest)
        assert env.dependencies == {}
        assert env.errors == []

    @pytest.mark.asyncio
    async def test_missing_config_returns_empty_deps(self, tmp_path: Path):
        manifest = ProjectManifest(
            root_path=tmp_path,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java")
            ],
        )
        env = await resolve_dependencies(manifest)
        # No pom.xml at tmp_path, so java deps should be empty
        assert env.dependencies.get("java", []) == []

    @pytest.mark.asyncio
    async def test_parse_exception_records_error(self, tmp_path: Path):
        """When a parser raises an unexpected exception, the error is recorded."""
        from unittest.mock import patch

        manifest = ProjectManifest(
            root_path=tmp_path,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java")
            ],
        )
        with patch(
            "app.stages.dependencies.parse_maven_dependencies",
            side_effect=RuntimeError("boom"),
        ):
            env = await resolve_dependencies(manifest)
        assert env.dependencies.get("java", []) == []
        assert len(env.errors) == 1
        assert "boom" in env.errors[0]

    @pytest.mark.asyncio
    async def test_multiple_build_tools(self, tmp_path: Path):
        # Create both pom.xml and package.json
        pom = tmp_path / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.google.guava</groupId>\n"
            "      <artifactId>guava</artifactId>\n"
            "      <version>32.1.3-jre</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"lodash": "^4.17.21"}}')

        manifest = ProjectManifest(
            root_path=tmp_path,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java"),
                BuildTool(
                    name="npm",
                    config_file="package.json",
                    language="javascript",
                ),
            ],
        )
        env = await resolve_dependencies(manifest)
        assert "java" in env.dependencies
        assert "javascript" in env.dependencies


# -- Python venv builder ──────────────────────────────────────────


class TestBuildPythonVenv:
    @pytest.fixture
    def python_project(self, tmp_path: Path) -> Path:
        """Create a minimal Python project with requirements.txt."""
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
        return tmp_path

    def test_creates_venv_directory(self, python_project: Path, monkeypatch):
        """On success, build_python_venv returns the venv path which must exist."""
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            # Simulate uv venv creating the directory
            if cmd[:2] == ["uv", "venv"]:
                Path(cmd[2]).mkdir(parents=True, exist_ok=True)
                (Path(cmd[2]) / "bin").mkdir(exist_ok=True)
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        venv = build_python_venv(python_project)

        assert venv is not None
        assert venv.exists()
        # First call should be uv venv
        assert calls[0][:2] == ["uv", "venv"]
        # Second call should be uv pip install
        assert any(c[:3] == ["uv", "pip", "install"] for c in calls)
