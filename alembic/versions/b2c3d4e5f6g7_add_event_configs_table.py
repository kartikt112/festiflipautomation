"""Add event_configs table

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'event_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_keyword', sa.String(length=255), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=True),
        sa.Column('min_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('max_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('ask_edition', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_event_configs_event_keyword', 'event_configs', ['event_keyword'])


def downgrade() -> None:
    op.drop_index('ix_event_configs_event_keyword')
    op.drop_table('event_configs')
