"""create sent_email table

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-16 12:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sent_email',
        sa.Column('id', sa.VARCHAR(36), primary_key=True, server_default=sa.text('gen_random_uuid()::varchar')),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('trigger_type', sa.Text(), nullable=False),
        sa.Column('license_jti', sa.Text(), nullable=False),
        sa.Column('subject', sa.Text(), nullable=False),
        sa.Column('recipients', JSONB(), nullable=False),
        sa.Column('delivery_status', sa.Text(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
    )

    op.create_index(
        'ix_sent_email_dedup',
        'sent_email',
        ['trigger_type', 'license_jti', sa.text('sent_at DESC')],
    )
    op.create_index(
        'ix_sent_email_sent_at',
        'sent_email',
        [sa.text('sent_at DESC')],
    )


def downgrade() -> None:
    op.drop_index('ix_sent_email_sent_at', table_name='sent_email')
    op.drop_index('ix_sent_email_dedup', table_name='sent_email')
    op.drop_table('sent_email')
