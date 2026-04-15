"""add total_loc to analysis_runs

Revision ID: 566c6d70dfeb
Revises: 516b8152252f
Create Date: 2026-04-16 02:25:08.419515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '566c6d70dfeb'
down_revision: Union[str, Sequence[str], None] = '516b8152252f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_runs', sa.Column('total_loc', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('analysis_runs', 'total_loc')
