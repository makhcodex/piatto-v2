"""Add contact fields to orders

Recipient name and phone, captured per order rather than on the user profile.
Nullable so existing rows need no backfill.

Revision ID: c7d2e81f4a56
Revises: a1c4f9e27b30
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7d2e81f4a56'
down_revision: Union[str, None] = 'a1c4f9e27b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('contact_name', sa.String(length=64), nullable=True))
    op.add_column('orders', sa.Column('contact_phone', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'contact_phone')
    op.drop_column('orders', 'contact_name')
