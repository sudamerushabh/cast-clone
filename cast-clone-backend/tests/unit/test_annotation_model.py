"""Tests for Annotation and Tag SQLAlchemy models."""
from app.models.db import Annotation, Tag


def test_annotation_model_fields():
    ann = Annotation(
        project_id="proj-1",
        node_fqn="com.app.UserService",
        content="This service is being deprecated in Q3",
        author_id="user-1",
    )
    assert ann.project_id == "proj-1"
    assert ann.node_fqn == "com.app.UserService"
    assert ann.content == "This service is being deprecated in Q3"
    assert ann.author_id == "user-1"


def test_annotation_tablename():
    assert Annotation.__tablename__ == "annotations"


def test_tag_model_fields():
    tag = Tag(
        project_id="proj-1",
        node_fqn="com.app.UserService",
        tag_name="deprecated",
        author_id="user-1",
    )
    assert tag.tag_name == "deprecated"


def test_tag_tablename():
    assert Tag.__tablename__ == "tags"
