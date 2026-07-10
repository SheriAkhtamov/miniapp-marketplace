"""Category images/order, banner products and popular products

Revision ID: 009
"""
from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"


def upgrade():
    op.add_column("categories", sa.Column("image_path", sa.String(), nullable=True))
    op.add_column(
        "categories",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_categories_sort_order", "categories", ["sort_order"], unique=False)

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE categories SET sort_order = id WHERE sort_order = 0"))

    op.add_column(
        "products",
        sa.Column("is_popular", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "products",
        sa.Column("popular_sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_products_is_popular", "products", ["is_popular"], unique=False)
    op.create_index(
        "ix_products_popular_sort_order",
        "products",
        ["popular_sort_order"],
        unique=False,
    )

    op.create_table(
        "promo_banner_products",
        sa.Column(
            "banner_id",
            sa.Integer(),
            sa.ForeignKey("promo_banners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("banner_id", "product_id"),
    )
    op.create_index(
        "ix_promo_banner_products_product_id",
        "promo_banner_products",
        ["product_id"],
        unique=False,
    )

    op.alter_column("categories", "sort_order", server_default=None)
    op.alter_column("products", "is_popular", server_default=None)
    op.alter_column("products", "popular_sort_order", server_default=None)


def downgrade():
    op.drop_index("ix_promo_banner_products_product_id", table_name="promo_banner_products")
    op.drop_table("promo_banner_products")

    op.drop_index("ix_products_popular_sort_order", table_name="products")
    op.drop_index("ix_products_is_popular", table_name="products")
    op.drop_column("products", "popular_sort_order")
    op.drop_column("products", "is_popular")

    op.drop_index("ix_categories_sort_order", table_name="categories")
    op.drop_column("categories", "sort_order")
    op.drop_column("categories", "image_path")
