"""Tests for saved view Pydantic schemas."""
import pytest
from pydantic import ValidationError
from app.schemas.saved_views import SavedViewCreate, SavedViewResponse, SavedViewUpdate


def test_create_valid():
    req = SavedViewCreate(
        name="My View",
        state={"viewType": "architecture", "zoom": 1.0},
    )
    assert req.name == "My View"


def test_create_with_description():
    req = SavedViewCreate(
        name="My View",
        description="A saved view for the team",
        state={"viewType": "architecture"},
    )
    assert req.description == "A saved view for the team"


def test_create_empty_name():
    with pytest.raises(ValidationError):
        SavedViewCreate(name="", state={})


def test_update_valid():
    req = SavedViewUpdate(name="Updated Name")
    assert req.name == "Updated Name"
    assert req.state is None


def test_update_state_only():
    req = SavedViewUpdate(state={"viewType": "dependency"})
    assert req.state == {"viewType": "dependency"}
