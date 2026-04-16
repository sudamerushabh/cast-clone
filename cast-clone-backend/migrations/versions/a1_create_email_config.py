"""create email_config table

Revision ID: a1b2c3d4e5f6
Revises: 566c6d70dfeb
Create Date: 2026-04-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '566c6d70dfeb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_config',
        sa.Column('id', sa.VARCHAR(36), primary_key=True, server_default=sa.text('gen_random_uuid()::varchar')),
        sa.Column('singleton', sa.Boolean(), nullable=False, unique=True, server_default=sa.text('true')),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('smtp_host', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('smtp_port', sa.Integer(), nullable=False, server_default=sa.text('587')),
        sa.Column('smtp_username', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('smtp_password_encrypted', sa.LargeBinary(), nullable=True),
        sa.Column('smtp_use_tls', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('from_address', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('from_name', sa.Text(), nullable=False, server_default=sa.text("'ChangeSafe'")),
        sa.Column('recipients', JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('flentas_bcc_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('cadence', sa.Text(), nullable=False, server_default=sa.text("'off'")),
        sa.Column('cadence_day', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('cadence_hour_utc', sa.Integer(), nullable=False, server_default=sa.text('9')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('email_config')
