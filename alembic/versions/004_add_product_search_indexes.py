"""Add PostgreSQL full-text and trigram indexes for product search

Revision ID: 004
"""
from alembic import op


revision = "004"
down_revision = "003"


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_search_ru_tsv
        ON products
        USING gin (
            to_tsvector(
                'russian',
                coalesce(name_ru, '') || ' ' || coalesce(description_ru, '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_search_uz_tsv
        ON products
        USING gin (
            to_tsvector(
                'simple',
                coalesce(name_uz, '') || ' ' || coalesce(description_uz, '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_name_ru_trgm
        ON products
        USING gin (lower(name_ru) gin_trgm_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_name_uz_trgm
        ON products
        USING gin (lower(name_uz) gin_trgm_ops)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_products_name_uz_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_name_ru_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_search_uz_tsv")
    op.execute("DROP INDEX IF EXISTS ix_products_search_ru_tsv")
