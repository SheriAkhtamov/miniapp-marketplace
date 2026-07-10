"""Add admin_unread to orders

Revision ID: 008
"""
from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"


def upgrade():
    op.add_column(
        "orders",
        sa.Column("admin_unread", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_orders_admin_unread", "orders", ["admin_unread"], unique=False)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE orders
            SET admin_unread = FALSE
            WHERE status <> 'new'
            """
        )
    )


def downgrade():
    op.drop_index("ix_orders_admin_unread", table_name="orders")
    op.drop_column("orders", "admin_unread")
