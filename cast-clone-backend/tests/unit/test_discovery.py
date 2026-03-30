"""Tests for Stage 1: Project Discovery."""

from pathlib import Path

import pytest

from app.models.enums import Confidence
from app.models.manifest import (
    ProjectManifest,
)
from app.stages.discovery import (
    count_loc,
    detect_build_tools,
    detect_frameworks,
    detect_language,
    discover_project,
    walk_source_files,
)

# -- Language Detection ────────────────────────────────────────────


class TestDetectLanguage:
    def test_java_extension(self):
        assert detect_language(Path("Foo.java")) == "java"

    def test_python_extension(self):
        assert detect_language(Path("main.py")) == "python"

    def test_typescript_extension(self):
        assert detect_language(Path("app.ts")) == "typescript"

    def test_tsx_extension(self):
        assert detect_language(Path("Component.tsx")) == "typescript"

    def test_javascript_extension(self):
        assert detect_language(Path("index.js")) == "javascript"

    def test_jsx_extension(self):
        assert detect_language(Path("App.jsx")) == "javascript"

    def test_csharp_extension(self):
        assert detect_language(Path("Program.cs")) == "csharp"

    def test_sql_extension(self):
        assert detect_language(Path("migration.sql")) == "sql"

    def test_unknown_extension_returns_none(self):
        assert detect_language(Path("README.md")) is None

    def test_no_extension_returns_none(self):
        assert detect_language(Path("Makefile")) is None


# -- LOC Counting ─────────────────────────────────────────────────


class TestCountLoc:
    def test_counts_non_empty_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("public class Foo {\n    int x = 1;\n}\n")
        assert count_loc(f) == 3

    def test_skips_empty_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("line1\n\n\nline2\n")
        assert count_loc(f) == 2

    def test_skips_whitespace_only_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("line1\n   \n\t\nline2\n")
        assert count_loc(f) == 2

    def test_skips_double_slash_comments(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("// this is a comment\nint x = 1;\n// another comment\n")
        assert count_loc(f) == 1

    def test_skips_hash_comments(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("# comment\nx = 1\n# another\ny = 2\n")
        assert count_loc(f) == 2

    def test_skips_block_comment_markers(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("/*\n * block comment\n */\nint x = 1;\n")
        assert count_loc(f) == 1

    def test_skips_sql_dash_comments(self, tmp_path: Path):
        f = tmp_path / "test.sql"
        f.write_text("-- comment\nSELECT * FROM users;\n-- end\n")
        assert count_loc(f) == 1

    def test_empty_file_returns_zero(self, tmp_path: Path):
        f = tmp_path / "empty.java"
        f.write_text("")
        assert count_loc(f) == 0

    def test_binary_file_returns_zero(self, tmp_path: Path):
        f = tmp_path / "binary.java"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        assert count_loc(f) == 0


# -- Filesystem Walk ──────────────────────────────────────────────


class TestWalkSourceFiles:
    def test_finds_java_files(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        java_files = [f for f in files if f.language == "java"]
        assert len(java_files) == 2  # UserService.java, UserController.java

    def test_skips_hidden_dirs(self, tmp_path: Path):
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "Foo.java").write_text("class Foo {}")
        normal = tmp_path / "src"
        normal.mkdir()
        (normal / "Bar.java").write_text("class Bar {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].path == "src/Bar.java"

    def test_skips_build_output_dirs(self, tmp_path: Path):
        for skip_dir in ["node_modules", "target", "build", "__pycache__"]:
            d = tmp_path / skip_dir
            d.mkdir()
            (d / "Foo.java").write_text("class Foo {}")
        src = tmp_path / "src"
        src.mkdir()
        (src / "Main.java").write_text("class Main {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1

    def test_returns_relative_paths(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        for f in files:
            assert not Path(f.path).is_absolute()
            assert f.path.startswith("src/")

    def test_includes_size_bytes(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        for f in files:
            assert f.size_bytes > 0

    def test_ignores_unknown_extensions(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "Main.java").write_text("class Main {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].language == "java"


# -- Build Tool Detection ─────────────────────────────────────────


class TestDetectBuildTools:
    def test_detects_maven(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        maven_tools = [t for t in tools if t.name == "maven"]
        assert len(maven_tools) == 1
        assert maven_tools[0].config_file == "pom.xml"
        assert maven_tools[0].language == "java"

    def test_detects_npm(self, express_app_dir: Path):
        tools = detect_build_tools(express_app_dir)
        npm_tools = [t for t in tools if t.name == "npm"]
        assert len(npm_tools) == 1
        assert npm_tools[0].config_file == "package.json"

    def test_detects_gradle(self, tmp_path: Path):
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "gradle" for t in tools)

    def test_detects_gradle_kts(self, tmp_path: Path):
        (tmp_path / "build.gradle.kts").write_text("plugins { java }")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "gradle" for t in tools)

    def test_detects_pyproject(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "uv/pip" for t in tools)

    def test_detects_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask==3.0.0\n")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "pip" for t in tools)

    def test_detects_setup_py(self, tmp_path: Path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "pip" for t in tools)

    def test_detects_dotnet_csproj(self, tmp_path: Path):
        (tmp_path / "MyApp.csproj").write_text("<Project></Project>")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "dotnet" for t in tools)

    def test_detects_dotnet_sln(self, tmp_path: Path):
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "dotnet" for t in tools)

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        tools = detect_build_tools(tmp_path)
        assert tools == []


# -- Framework Detection ──────────────────────────────────────────


class TestDetectFrameworks:
    def test_detects_spring_boot_from_pom(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        spring = [f for f in frameworks if f.name == "spring-boot"]
        assert len(spring) == 1
        assert spring[0].confidence == Confidence.HIGH
        assert spring[0].language == "java"

    def test_detects_hibernate_from_pom(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        hibernate = [f for f in frameworks if f.name == "hibernate"]
        assert len(hibernate) == 1
        assert hibernate[0].confidence == Confidence.HIGH

    def test_detects_spring_data_jpa(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        jpa = [f for f in frameworks if f.name == "spring-data-jpa"]
        assert len(jpa) == 1

    def test_detects_express_from_package_json(self, express_app_dir: Path):
        tools = detect_build_tools(express_app_dir)
        frameworks = detect_frameworks(express_app_dir, tools)
        express = [f for f in frameworks if f.name == "express"]
        assert len(express) == 1
        assert express[0].confidence == Confidence.HIGH
        assert express[0].language == "javascript"

    def test_detects_react_from_package_json(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"react": "^18.2.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        react = [f for f in frameworks if f.name == "react"]
        assert len(react) == 1

    def test_detects_nestjs(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"@nestjs/core": "^10.0.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        nest = [f for f in frameworks if f.name == "nestjs"]
        assert len(nest) == 1

    def test_detects_angular(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"@angular/core": "^17.0.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        angular = [f for f in frameworks if f.name == "angular"]
        assert len(angular) == 1

    def test_detects_django_from_requirements(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("django==5.0\ncelery==5.3.4\n")
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        django = [f for f in frameworks if f.name == "django"]
        assert len(django) == 1
        assert django[0].language == "python"

    def test_detects_fastapi_from_pyproject(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        content = (
            '[project]\nname = "myapp"\n'
            'dependencies = ["fastapi>=0.104.0", "uvicorn"]\n'
        )
        toml.write_text(content)
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        fastapi = [f for f in frameworks if f.name == "fastapi"]
        assert len(fastapi) == 1

    def test_detects_aspnet_from_csproj(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk.Web">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.AspNetCore.OpenApi" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        aspnet = [f for f in frameworks if f.name == "aspnet"]
        assert len(aspnet) == 1
        assert aspnet[0].language == "csharp"

    def test_no_frameworks_in_empty_project(self, tmp_path: Path):
        frameworks = detect_frameworks(tmp_path, [])
        assert frameworks == []

    def test_detects_aspnet_from_sln_with_nested_csproj(self, tmp_path: Path):
        """When a .sln file is at root and .csproj files are nested deeper,
        the framework detection should recursively scan all .csproj files."""
        # Create .sln at root
        sln = tmp_path / "MySolution.sln"
        sln.write_text("Microsoft Visual Studio Solution File\n")

        # Create nested .csproj with ASP.NET reference (2 levels deep)
        web_dir = tmp_path / "src" / "MyApp.WebHost"
        web_dir.mkdir(parents=True)
        csproj = web_dir / "MyApp.WebHost.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk.Web">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.AspNetCore.OpenApi" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )

        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        aspnet = [f for f in frameworks if f.name == "aspnet"]
        assert len(aspnet) == 1
        assert aspnet[0].language == "csharp"
        assert aspnet[0].confidence == Confidence.HIGH

    def test_detects_efcore_from_sln_with_nested_csproj(self, tmp_path: Path):
        """EF Core detection via recursive .csproj scanning."""
        sln = tmp_path / "MySolution.sln"
        sln.write_text("Microsoft Visual Studio Solution File\n")

        data_dir = tmp_path / "src" / "MyApp.Data"
        data_dir.mkdir(parents=True)
        csproj = data_dir / "MyApp.Data.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.EntityFrameworkCore" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )

        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        ef = [f for f in frameworks if f.name == "efcore"]
        assert len(ef) == 1


# -- Full Discovery Integration ───────────────────────────────────


class TestDiscoverProject:
    def test_discovers_raw_java(self, raw_java_dir: Path):
        manifest = discover_project(raw_java_dir)
        assert isinstance(manifest, ProjectManifest)
        assert manifest.root_path == raw_java_dir
        assert manifest.total_files == 2
        assert manifest.total_loc > 0
        assert manifest.has_language("java")
        assert len(manifest.build_tools) == 1
        assert manifest.build_tools[0].name == "maven"

    def test_discovers_express_app(self, express_app_dir: Path):
        manifest = discover_project(express_app_dir)
        assert manifest.total_files == 1  # Only .js file, not package.json
        assert manifest.has_language("javascript")
        assert any(f.name == "express" for f in manifest.detected_frameworks)

    def test_discovers_spring_petclinic(self, spring_petclinic_dir: Path):
        manifest = discover_project(spring_petclinic_dir)
        assert manifest.total_files >= 11  # 10 Java + 1 SQL
        assert manifest.has_language("java")
        # Should detect spring-boot
        framework_names = [f.name for f in manifest.detected_frameworks]
        assert "spring-boot" in framework_names

    def test_language_stats_are_aggregated(self, spring_petclinic_dir: Path):
        manifest = discover_project(spring_petclinic_dir)
        java_lang = next(
            lang for lang in manifest.detected_languages if lang.name == "java"
        )
        assert java_lang.file_count >= 10
        assert java_lang.total_loc > 0

    def test_manifest_total_loc_matches_sum(self, raw_java_dir: Path):
        manifest = discover_project(raw_java_dir)
        lang_loc_sum = sum(lang.total_loc for lang in manifest.detected_languages)
        assert manifest.total_loc == lang_loc_sum

    def test_empty_directory(self, tmp_path: Path):
        manifest = discover_project(tmp_path)
        assert manifest.total_files == 0
        assert manifest.total_loc == 0
        assert manifest.detected_languages == []
        assert manifest.detected_frameworks == []
        assert manifest.build_tools == []

    def test_nonexistent_path_raises(self):
        with pytest.raises(FileNotFoundError):
            discover_project(Path("/nonexistent/path/that/does/not/exist"))

    def test_file_path_raises_not_a_directory(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with pytest.raises(NotADirectoryError):
            discover_project(f)
