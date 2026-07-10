"""Add app settings

Revision ID: 010
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.alter_column("app_settings", "updated_at", server_default=None)


def downgrade():
    op.drop_table("app_settings")
