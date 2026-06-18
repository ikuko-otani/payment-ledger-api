"""add_currency_fk_to_accounts_entries

Revision ID: d117489c7a4b
Revises: ee54b717aba2
Create Date: 2026-06-18 18:56:48.666924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd117489c7a4b'
down_revision: Union[str, None] = 'ee54b717aba2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
