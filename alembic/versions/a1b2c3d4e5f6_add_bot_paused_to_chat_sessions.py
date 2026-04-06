"""Add bot_paused to chat_sessions

Revision ID: a1b2c3d4e5f6
Revises: 17a70e64c3bf
Create Date: 2026-04-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '17a70e64c3bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('bot_paused', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'bot_paused')
