"""Add sell_type and pack_quantity to products

Revision ID: 003
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002_manual_orders'

def upgrade():
    op.add_column('products', sa.Column('sell_type', sa.String(), server_default='piece', nullable=False))
    op.add_column('products', sa.Column('pack_quantity', sa.Integer(), nullable=True))

def downgrade():
    op.drop_column('products', 'pack_quantity')
    op.drop_column('products', 'sell_type')
