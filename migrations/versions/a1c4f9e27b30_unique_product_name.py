"""unique product name

Gives products a natural key so seeding can upsert on it.

Revision ID: a1c4f9e27b30
Revises: 00ba32237596
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c4f9e27b30'
down_revision: Union[str, None] = '00ba32237596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_products_name', 'products', ['name'])


def downgrade() -> None:
    op.drop_constraint('uq_products_name', 'products', type_='unique')
