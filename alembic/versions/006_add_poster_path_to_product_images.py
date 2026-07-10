"""Add poster_path to product_images

Revision ID: 006
"""
from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"


def upgrade():
    op.add_column(
        "product_images",
        sa.Column("poster_path", sa.String(), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id
            FROM products
            WHERE lower(coalesce(image_path, '')) ~ :pattern
            """
        ),
        {"pattern": r"\.(mp4|webm|mov|avi)$"},
    ).fetchall()

    for row in rows:
        replacement = conn.execute(
            sa.text(
                """
                SELECT id, image_path
                FROM product_images
                WHERE product_id = :product_id
                  AND coalesce(media_type, 'image') = 'image'
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                """
            ),
            {"product_id": row.id},
        ).fetchone()

        if replacement:
            conn.execute(
                sa.text(
                    """
                    UPDATE products
                    SET image_path = :image_path
                    WHERE id = :product_id
                    """
                ),
                {"product_id": row.id, "image_path": replacement.image_path},
            )
            conn.execute(
                sa.text("DELETE FROM product_images WHERE id = :image_id"),
                {"image_id": replacement.id},
            )
        else:
            conn.execute(
                sa.text(
                    """
                    UPDATE products
                    SET image_path = ''
                    WHERE id = :product_id
                    """
                ),
                {"product_id": row.id},
            )


def downgrade():
    op.drop_column("product_images", "poster_path")
