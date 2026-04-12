"""Add whatsapp_groups table and seed existing group

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-04-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'whatsapp_groups',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('group_id', sa.String(length=100), nullable=False),
        sa.Column('group_name', sa.String(length=255), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('auto_detected', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_whatsapp_groups_group_id', 'whatsapp_groups', ['group_id'], unique=True)

    # Seed the existing hardcoded group so there's no behavior change on deploy
    op.execute(
        "INSERT INTO whatsapp_groups (group_id, group_name, enabled, auto_detected) "
        "VALUES ('120363423980604716@g.us', 'FestiFlip Operations', 1, 0)"
    )


def downgrade() -> None:
    op.drop_index('ix_whatsapp_groups_group_id')
    op.drop_table('whatsapp_groups')
