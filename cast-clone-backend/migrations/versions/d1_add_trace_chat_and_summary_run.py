"""add ai trace chat table + analysis_run_id/updated_at to ai_summaries

Revision ID: d1a2b3c4e5f6
Revises: c1d2e3f4a5b6
Create Date: 2026-04-16 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ai_summaries: track which analysis run produced the cached
    #    summary and when it was last written.
    op.add_column(
        "ai_summaries",
        sa.Column("analysis_run_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_summaries_analysis_run",
        "ai_summaries",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "ai_summaries",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── ai_trace_chat_messages: follow-up Q&A threads per trace node.
    op.create_table(
        "ai_trace_chat_messages",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()::varchar"),
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_run_id",
            sa.String(36),
            sa.ForeignKey("analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("node_fqn", sa.String(500), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("graph_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_trace_chat_project_node_created",
        "ai_trace_chat_messages",
        ["project_id", "node_fqn", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trace_chat_project_node_created",
        table_name="ai_trace_chat_messages",
    )
    op.drop_table("ai_trace_chat_messages")
    op.drop_column("ai_summaries", "updated_at")
    op.drop_constraint(
        "fk_ai_summaries_analysis_run", "ai_summaries", type_="foreignkey"
    )
    op.drop_column("ai_summaries", "analysis_run_id")
