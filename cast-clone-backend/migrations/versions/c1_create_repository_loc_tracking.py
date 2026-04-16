"""create repository_loc_tracking table with backfill

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create table
    op.create_table(
        "repository_loc_tracking",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("billable_loc", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "max_loc_project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("max_loc_branch_name", sa.String(255), nullable=True),
        sa.Column(
            "breakdown",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "last_recalculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # 2. Backfill from existing completed analysis runs
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO repository_loc_tracking
            (id, repository_id, billable_loc, max_loc_project_id,
             max_loc_branch_name, breakdown, last_recalculated_at, created_at)
        SELECT
            gen_random_uuid()::text,
            r.id,
            COALESCE(agg.max_loc, 0),
            agg.max_project_id,
            agg.max_branch,
            COALESCE(agg.breakdown, '{}'::jsonb),
            NOW(),
            NOW()
        FROM repositories r
        LEFT JOIN LATERAL (
            SELECT
                max_row.total_loc AS max_loc,
                max_row.project_id AS max_project_id,
                max_row.branch AS max_branch,
                jsonb_object_agg(
                    COALESCE(branch_locs.branch, 'unknown'),
                    branch_locs.loc
                ) AS breakdown
            FROM (
                SELECT DISTINCT ON (p2.id)
                    p2.id AS project_id,
                    p2.branch,
                    ar2.total_loc AS loc
                FROM projects p2
                JOIN analysis_runs ar2 ON ar2.project_id = p2.id
                WHERE p2.repository_id = r.id
                  AND ar2.status = 'completed'
                  AND ar2.total_loc IS NOT NULL
                ORDER BY p2.id, ar2.completed_at DESC
            ) branch_locs
            CROSS JOIN LATERAL (
                SELECT branch_locs.project_id, branch_locs.branch,
                       branch_locs.loc AS total_loc
                FROM (
                    SELECT DISTINCT ON (p3.id)
                        p3.id AS project_id,
                        p3.branch,
                        ar3.total_loc AS loc
                    FROM projects p3
                    JOIN analysis_runs ar3 ON ar3.project_id = p3.id
                    WHERE p3.repository_id = r.id
                      AND ar3.status = 'completed'
                      AND ar3.total_loc IS NOT NULL
                    ORDER BY p3.id, ar3.completed_at DESC
                ) sub
                ORDER BY sub.loc DESC
                LIMIT 1
            ) max_row
            GROUP BY max_row.total_loc, max_row.project_id, max_row.branch
        ) agg ON true
    """))


def downgrade() -> None:
    op.drop_table("repository_loc_tracking")
