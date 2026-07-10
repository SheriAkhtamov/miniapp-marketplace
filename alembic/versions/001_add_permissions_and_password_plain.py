"""add permissions and password_plain to users

Revision ID: 001_permissions
Revises: 
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = '001_permissions'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_plain', sa.String(), nullable=True))
    op.add_column('users', sa.Column('permissions', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'permissions')
    op.drop_column('users', 'password_plain')
