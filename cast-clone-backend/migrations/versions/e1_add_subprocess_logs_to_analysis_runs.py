"""add subprocess_logs to analysis_runs

CHAN-72: persist paths of overflow temp files produced when a subprocess
(e.g. a SCIP indexer or Maven build) exceeds the 10MB per-stream
in-memory capture cap. Stored as JSONB array of
``{stream, path, size_bytes}`` dicts so operators can find and inspect
the full logs post-run.

Revision ID: e1a2b3c4d5f7
Revises: d1a2b3c4e5f6
Create Date: 2026-04-22 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f7"
down_revision: str | Sequence[str] | None = "d1a2b3c4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("subprocess_logs", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "subprocess_logs")
