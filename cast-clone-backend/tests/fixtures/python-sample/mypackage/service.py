"""User service module."""

import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class BaseService:
    """Abstract base for all services."""

    def __init__(self, db: Session):
        self.db = db


@dataclass
class UserService(BaseService):
    """Manages user operations."""

    DEFAULT_PAGE_SIZE = 20

    def __init__(self, db: Session, cache: Optional[object] = None):
        super().__init__(db)
        self.cache = cache
        self._initialized = True

    def find_by_email(self, email: str) -> Optional[dict]:
        """Find a user by email address."""
        query = "SELECT id, name, email FROM users WHERE email = :email"
        result = self.db.execute(query, {"email": email})
        logger.info("Looked up user by email")
        return result.first()

    def count_active(self) -> int:
        sql = "SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL"
        return self.db.execute(sql).scalar()

    @staticmethod
    def validate_email(email: str) -> bool:
        return "@" in email


def create_service(db: Session) -> UserService:
    """Factory function for UserService."""
    return UserService(db)
