"""Add order delivery pricing fields

Revision ID: 013
"""
from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"


def upgrade():
    op.add_column("orders", sa.Column("delivery_option_id", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("delivery_option_name", sa.String(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("delivery_price", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("orders", "delivery_price", server_default=None)


def downgrade():
    op.drop_column("orders", "delivery_price")
    op.drop_column("orders", "delivery_option_name")
    op.drop_column("orders", "delivery_option_id")
