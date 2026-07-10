"""Add order delivery location coordinates

Revision ID: 015
"""
from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"


def upgrade():
    op.add_column("orders", sa.Column("delivery_latitude", sa.Float(), nullable=True))
    op.add_column("orders", sa.Column("delivery_longitude", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("orders", "delivery_longitude")
    op.drop_column("orders", "delivery_latitude")
