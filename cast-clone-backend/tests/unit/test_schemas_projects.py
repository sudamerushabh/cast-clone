# tests/unit/test_schemas_projects.py
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.projects import (
    ProjectCreate,
    ProjectResponse,
    ProjectListResponse,
)


class TestProjectCreate:
    def test_valid_create(self):
        data = ProjectCreate(name="my-project", source_path="/opt/code/my-project")
        assert data.name == "my-project"
        assert data.source_path == "/opt/code/my-project"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate(source_path="/opt/code/my-project")

    def test_source_path_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="my-project")

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="", source_path="/opt/code")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="x" * 256, source_path="/opt/code")

    def test_source_path_min_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="proj", source_path="")


class TestProjectResponse:
    def test_from_dict(self):
        now = datetime.now()
        resp = ProjectResponse(
            id="abc-123",
            name="my-project",
            source_path="/opt/code/my-project",
            status="created",
            created_at=now,
            updated_at=now,
        )
        assert resp.id == "abc-123"
        assert resp.status == "created"

    def test_serialization(self):
        now = datetime.now()
        resp = ProjectResponse(
            id="abc-123",
            name="my-project",
            source_path="/opt/code/my-project",
            status="created",
            created_at=now,
            updated_at=now,
        )
        data = resp.model_dump()
        assert "id" in data
        assert "name" in data


class TestProjectListResponse:
    def test_empty_list(self):
        resp = ProjectListResponse(projects=[], total=0)
        assert resp.projects == []
        assert resp.total == 0
