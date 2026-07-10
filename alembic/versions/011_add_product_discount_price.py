"""Add product discount price

Revision ID: 011
"""
from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"


def upgrade():
    op.add_column("products", sa.Column("discount_price", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("products", "discount_price")
