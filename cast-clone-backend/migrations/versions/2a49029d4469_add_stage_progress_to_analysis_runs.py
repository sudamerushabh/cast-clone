"""add stage_progress to analysis_runs

Revision ID: 2a49029d4469
Revises:
Create Date: 2026-03-30 17:19:14.752043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2a49029d4469'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_runs', sa.Column('stage_progress', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('analysis_runs', 'stage_progress')
