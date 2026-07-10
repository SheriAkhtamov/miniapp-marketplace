"""Add normalized unique category name indexes

Revision ID: 012
"""
from alembic import op


revision = "012"
down_revision = "011"


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_name_ru_normalized "
        "ON categories (lower(btrim(name_ru)))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_name_uz_normalized "
        "ON categories (lower(btrim(name_uz)))"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_categories_name_uz_normalized")
    op.execute("DROP INDEX IF EXISTS uq_categories_name_ru_normalized")
