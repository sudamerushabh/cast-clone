"""Tests for annotation and tag Pydantic schemas."""
import pytest
from pydantic import ValidationError

from app.schemas.annotations import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
    TagCreate,
    TagResponse,
    PREDEFINED_TAGS,
)


def test_annotation_create_valid():
    req = AnnotationCreate(node_fqn="com.app.UserService", content="Note here")
    assert req.node_fqn == "com.app.UserService"


def test_annotation_create_empty_content():
    with pytest.raises(ValidationError):
        AnnotationCreate(node_fqn="com.app.Foo", content="")


def test_annotation_update():
    req = AnnotationUpdate(content="Updated note")
    assert req.content == "Updated note"


def test_tag_create_valid():
    req = TagCreate(node_fqn="com.app.UserService", tag_name="deprecated")
    assert req.tag_name == "deprecated"


def test_tag_create_invalid_tag():
    with pytest.raises(ValidationError):
        TagCreate(node_fqn="com.app.Foo", tag_name="invalid-tag")


def test_predefined_tags_exist():
    assert "deprecated" in PREDEFINED_TAGS
    assert "tech-debt" in PREDEFINED_TAGS
    assert "critical-path" in PREDEFINED_TAGS
    assert "security-sensitive" in PREDEFINED_TAGS
    assert "needs-review" in PREDEFINED_TAGS
