"""Add is_active to categories

Revision ID: 007
"""
from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"


def upgrade():
    op.add_column(
        "categories",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("categories", "is_active", server_default=None)


def downgrade():
    op.drop_column("categories", "is_active")
