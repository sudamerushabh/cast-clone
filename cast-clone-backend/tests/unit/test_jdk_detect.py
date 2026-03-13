"""Tests for JDK version auto-detection."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.stages.scip.jdk_detect import (
    _extract_version_from_dirname,
    _parse_gradle_java_version,
    _parse_pom_java_version,
    detect_java_version,
    find_installed_jdks,
    resolve_java_home,
)


class TestParseVersionFromDirname:
    def test_java_17_openjdk(self):
        assert _extract_version_from_dirname("java-17-openjdk-amd64") == 17

    def test_java_21_openjdk(self):
        assert _extract_version_from_dirname("java-21-openjdk-amd64") == 21

    def test_openjdk_21(self):
        assert _extract_version_from_dirname("openjdk-21") == 21

    def test_java_1_17(self):
        assert _extract_version_from_dirname("java-1.17.0-openjdk-amd64") == 17

    def test_jdk_17(self):
        assert _extract_version_from_dirname("jdk-17") == 17

    def test_sdkman_style(self):
        assert _extract_version_from_dirname("17.0.2-tem") == 17

    def test_unrecognized(self):
        assert _extract_version_from_dirname("default-java") is None


class TestParsePomJavaVersion:
    def test_java_version_tag(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(
            "<project><properties>"
            "<java.version>17</java.version>"
            "</properties></project>"
        )
        assert _parse_pom_java_version(pom) == 17

    def test_maven_compiler_source(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(
            "<project><properties>"
            "<maven.compiler.source>21</maven.compiler.source>"
            "</properties></project>"
        )
        assert _parse_pom_java_version(pom) == 21

    def test_maven_compiler_release(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(
            "<project><properties>"
            "<maven.compiler.release>11</maven.compiler.release>"
            "</properties></project>"
        )
        assert _parse_pom_java_version(pom) == 11

    def test_legacy_1_8(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(
            "<project><properties>"
            "<java.version>1.8</java.version>"
            "</properties></project>"
        )
        assert _parse_pom_java_version(pom) == 8

    def test_no_version(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text("<project></project>")
        assert _parse_pom_java_version(pom) is None

    def test_missing_file(self, tmp_path):
        assert _parse_pom_java_version(tmp_path / "nonexistent.xml") is None


class TestParseGradleJavaVersion:
    def test_source_compatibility(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("sourceCompatibility = 17\n")
        assert _parse_gradle_java_version(gradle) == 17

    def test_source_compatibility_quoted(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("sourceCompatibility = '21'\n")
        assert _parse_gradle_java_version(gradle) == 21

    def test_java_version_enum(self, tmp_path):
        gradle = tmp_path / "build.gradle.kts"
        gradle.write_text("java { sourceCompatibility = JavaVersion.VERSION_17 }\n")
        assert _parse_gradle_java_version(gradle) == 17

    def test_jvm_target(self, tmp_path):
        gradle = tmp_path / "build.gradle.kts"
        gradle.write_text('jvmTarget = "11"\n')
        assert _parse_gradle_java_version(gradle) == 11

    def test_no_version(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("apply plugin: 'java'\n")
        assert _parse_gradle_java_version(gradle) is None


class TestDetectJavaVersion:
    def test_pom_wins(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties><java.version>17</java.version></properties></project>"
        )
        assert detect_java_version(tmp_path) == 17

    def test_falls_back_to_gradle(self, tmp_path):
        (tmp_path / "build.gradle").write_text("sourceCompatibility = 21\n")
        assert detect_java_version(tmp_path) == 21

    def test_no_build_file(self, tmp_path):
        assert detect_java_version(tmp_path) is None


class TestFindInstalledJdks:
    def test_discovers_jdks(self, tmp_path):
        # Create fake JDK dirs
        jdk17 = tmp_path / "java-17-openjdk-amd64"
        jdk17.mkdir()
        (jdk17 / "bin").mkdir()
        (jdk17 / "bin" / "java").touch()

        jdk21 = tmp_path / "java-21-openjdk-amd64"
        jdk21.mkdir()
        (jdk21 / "bin").mkdir()
        (jdk21 / "bin" / "java").touch()

        with patch(
            "app.stages.scip.jdk_detect._JDK_SEARCH_PATHS", [tmp_path]
        ):
            jdks = find_installed_jdks()

        assert 17 in jdks
        assert 21 in jdks
        assert jdks[17] == jdk17

    def test_skips_non_jdk_dirs(self, tmp_path):
        (tmp_path / "not-a-jdk").mkdir()

        with patch(
            "app.stages.scip.jdk_detect._JDK_SEARCH_PATHS", [tmp_path]
        ):
            jdks = find_installed_jdks()

        assert len(jdks) == 0


class TestResolveJavaHome:
    def test_returns_env_when_different_jdk_needed(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties><java.version>17</java.version></properties></project>"
        )

        jdk17 = tmp_path / "jdks" / "java-17-openjdk-amd64"
        jdk17.mkdir(parents=True)
        (jdk17 / "bin").mkdir()
        (jdk17 / "bin" / "java").touch()

        with (
            patch(
                "app.stages.scip.jdk_detect._JDK_SEARCH_PATHS",
                [tmp_path / "jdks"],
            ),
            patch.dict(
                "os.environ",
                {"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64", "PATH": "/usr/bin"},
            ),
        ):
            result = resolve_java_home(tmp_path)

        assert result is not None
        assert result["JAVA_HOME"] == str(jdk17)
        assert str(jdk17 / "bin") in result["PATH"]

    def test_returns_none_when_already_matching(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties><java.version>21</java.version></properties></project>"
        )

        with patch.dict(
            "os.environ",
            {"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64"},
        ):
            result = resolve_java_home(tmp_path)

        assert result is None

    def test_returns_none_when_no_version_detected(self, tmp_path):
        result = resolve_java_home(tmp_path)
        assert result is None

    def test_returns_none_when_no_matching_jdk_installed(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties><java.version>11</java.version></properties></project>"
        )

        with (
            patch("app.stages.scip.jdk_detect._JDK_SEARCH_PATHS", []),
            patch.dict("os.environ", {"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64"}),
        ):
            result = resolve_java_home(tmp_path)

        assert result is None
