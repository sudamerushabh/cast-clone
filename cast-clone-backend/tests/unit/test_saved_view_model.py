"""Tests for SavedView SQLAlchemy model."""
from app.models.db import SavedView


def test_saved_view_model_fields():
    view = SavedView(
        project_id="proj-1",
        name="Architecture Overview",
        description="Main modules layout",
        author_id="user-1",
        state={"viewType": "architecture", "zoom": 1.5},
    )
    assert view.name == "Architecture Overview"
    assert view.state["viewType"] == "architecture"
    assert view.description == "Main modules layout"


def test_saved_view_tablename():
    assert SavedView.__tablename__ == "saved_views"


def test_saved_view_optional_description():
    view = SavedView(
        project_id="proj-1",
        name="Quick view",
        author_id="user-1",
        state={},
    )
    assert view.description is None
