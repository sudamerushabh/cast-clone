# tests/unit/test_manifest_models.py
from pathlib import Path

from app.models.enums import Confidence
from app.models.manifest import (
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    SourceFile,
)


class TestSourceFile:
    def test_create(self):
        sf = SourceFile(path="src/Main.java", language="java", size_bytes=1024)
        assert sf.language == "java"


class TestDetectedLanguage:
    def test_create(self):
        lang = DetectedLanguage(name="java", file_count=100, total_loc=5000)
        assert lang.name == "java"


class TestDetectedFramework:
    def test_create(self):
        fw = DetectedFramework(
            name="spring-boot",
            language="java",
            confidence=Confidence.HIGH,
            evidence=["pom.xml contains spring-boot-starter"],
        )
        assert fw.name == "spring-boot"
        assert fw.confidence == Confidence.HIGH


class TestProjectManifest:
    def test_create_empty(self):
        m = ProjectManifest(root_path=Path("/tmp/test"))
        assert m.total_files == 0
        assert m.total_loc == 0
        assert m.source_files == []

    def test_language_names(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            detected_languages=[
                DetectedLanguage(name="java", file_count=10, total_loc=1000),
                DetectedLanguage(name="python", file_count=5, total_loc=500),
            ],
        )
        assert m.language_names == ["java", "python"]

    def test_has_language(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            detected_languages=[
                DetectedLanguage(name="java", file_count=10, total_loc=1000),
            ],
        )
        assert m.has_language("java") is True
        assert m.has_language("python") is False

    def test_files_for_language(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            source_files=[
                SourceFile(path="A.java", language="java", size_bytes=100),
                SourceFile(path="B.py", language="python", size_bytes=200),
                SourceFile(path="C.java", language="java", size_bytes=300),
            ],
        )
        java_files = m.files_for_language("java")
        assert len(java_files) == 2
