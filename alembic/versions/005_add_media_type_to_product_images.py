"""Add media_type column to product_images table

Revision ID: 005
"""
from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"


def upgrade():
    op.add_column(
        "product_images",
        sa.Column("media_type", sa.String(), server_default="image", nullable=False),
    )


def downgrade():
    op.drop_column("product_images", "media_type")
