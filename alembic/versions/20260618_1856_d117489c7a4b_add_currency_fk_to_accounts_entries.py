"""add_currency_fk_to_accounts_entries

Revision ID: d117489c7a4b
Revises: ee54b717aba2
Create Date: 2026-06-18 18:56:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d117489c7a4b"
down_revision: Union[str, None] = "ee54b717aba2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Pre-check: ensure no orphaned currency codes exist before adding FK
    result = conn.execute(
        sa.text("""
            SELECT COUNT(*) FROM (
                SELECT currency FROM accounts
                WHERE currency NOT IN (SELECT code FROM currencies)
                UNION ALL
                SELECT currency FROM entries
                WHERE currency NOT IN (SELECT code FROM currencies)
            ) v
        """)
    )
    violations = result.scalar()
    if violations and violations > 0:
        raise RuntimeError(
            f"FK pre-check failed: {violations} row(s) have currency codes "
            "not found in currencies table. "
            "Resolve data inconsistencies before running this migration."
        )

    op.create_foreign_key(
        "fk_accounts_currency",
        "accounts", "currencies",
        ["currency"], ["code"],
    )
    op.create_foreign_key(
        "fk_entries_currency",
        "entries", "currencies",
        ["currency"], ["code"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_entries_currency", "entries", type_="foreignkey")
    op.drop_constraint("fk_accounts_currency", "accounts", type_="foreignkey")
