"""Add order payment receipt path

Revision ID: 014
"""
from alembic import op
import sqlalchemy as sa


revision = "014"
down_revision = "013"


def upgrade():
    op.add_column("orders", sa.Column("payment_receipt_path", sa.String(), nullable=True))


def downgrade():
    op.drop_column("orders", "payment_receipt_path")
