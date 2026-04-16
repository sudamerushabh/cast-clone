"""create deployment table

Revision ID: 516b8152252f
Revises: 2a49029d4469
Create Date: 2026-04-16 02:16:30.711793

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '516b8152252f'
down_revision: Union[str, Sequence[str], None] = '2a49029d4469'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Table name is singular by design — singleton table (max one row).
    op.create_table(
        'deployment',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column(
            'singleton', sa.Boolean(), nullable=False,
            server_default=sa.true(), unique=True,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table('deployment')
