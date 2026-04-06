"""Add group_post_queue table

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'group_post_queue',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sell_offer_id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(length=255), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=True),
        sa.Column('message_body', sa.String(length=2000), nullable=False),
        sa.Column('status', sa.Enum('QUEUED', 'POSTED', 'EXPIRED', name='poststatus'), nullable=False, server_default='QUEUED'),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_group_post_queue_sell_offer_id', 'group_post_queue', ['sell_offer_id'])


def downgrade() -> None:
    op.drop_index('ix_group_post_queue_sell_offer_id')
    op.drop_table('group_post_queue')
