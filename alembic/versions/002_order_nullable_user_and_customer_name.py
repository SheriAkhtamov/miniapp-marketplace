"""make order.user_id nullable and add customer_name

Revision ID: 002_manual_orders
Revises: 001_permissions
Create Date: 2026-02-18
"""
from alembic import op
import sqlalchemy as sa

revision = '002_manual_orders'
down_revision = '001_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('orders', 'user_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('orders', sa.Column('customer_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'customer_name')
    op.alter_column('orders', 'user_id', existing_type=sa.Integer(), nullable=False)
