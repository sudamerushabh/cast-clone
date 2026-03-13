"""Tests for ActivityLog SQLAlchemy model."""
from app.models.db import ActivityLog


def test_activity_log_fields():
    log = ActivityLog(
        user_id="user-1",
        action="user.login",
        resource_type="user",
        resource_id="user-1",
        details={"ip": "127.0.0.1"},
    )
    assert log.action == "user.login"
    assert log.resource_type == "user"
    assert log.details == {"ip": "127.0.0.1"}


def test_activity_log_tablename():
    assert ActivityLog.__tablename__ == "activity_log"


def test_activity_log_nullable_fields():
    log = ActivityLog(action="system.startup")
    assert log.user_id is None
    assert log.resource_type is None
    assert log.resource_id is None
    assert log.details is None
