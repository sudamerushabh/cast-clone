"""add todo.completed

Revision ID: 002_add_todo_completed
Revises: 001_initial
Create Date: 2026-01-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "002_add_todo_completed"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "todos",
        sa.Column("completed", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("todos", "completed")
