"""add_converted_amount_usd_to_entries

Revision ID: b067e55bdcf4
Revises: 6f551deab5c7
Create Date: 2026-05-27 10:41:30.249289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b067e55bdcf4'
down_revision: Union[str, None] = '6f551deab5c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add converted_amount_usd as NOT NULL.
    # server_default='0' satisfies the NOT NULL constraint for any pre-existing rows
    # during the migration; it is removed immediately after so future inserts must
    # supply the value explicitly (service layer always computes and provides it).
    op.add_column(
        "entries",
        sa.Column(
            "converted_amount_usd",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("entries", "converted_amount_usd", server_default=None)


def downgrade() -> None:
    op.drop_column("entries", "converted_amount_usd")
