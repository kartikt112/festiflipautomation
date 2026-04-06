"""Add reseller_inventory table

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-04-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reseller_inventory',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('reseller_id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(length=255), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=True),
        sa.Column('ticket_type', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('price_per_ticket', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.Enum('AVAILABLE', 'CHECKING', 'CONFIRMED', 'SOLD', 'UNAVAILABLE', name='inventorystatus'), nullable=False, server_default='AVAILABLE'),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_check_buyer_phone', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['reseller_id'], ['fixed_resellers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reseller_inventory_reseller_id', 'reseller_inventory', ['reseller_id'])
    op.create_index('ix_reseller_inventory_event_name', 'reseller_inventory', ['event_name'])


def downgrade() -> None:
    op.drop_index('ix_reseller_inventory_event_name')
    op.drop_index('ix_reseller_inventory_reseller_id')
    op.drop_table('reseller_inventory')
