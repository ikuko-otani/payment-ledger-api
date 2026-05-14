"""redesign_schema

Revision ID: 9004f7203189
Revises: 186facffe789
Create Date: 2026-05-14 15:36:08.632321

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9004f7203189"
down_revision: Union[str, None] = "186facffe789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ================================================================
    # accounts: add code, currency, is_active, updated_at
    # ================================================================
    op.add_column("accounts", sa.Column("code", sa.String(), nullable=True))
    op.create_unique_constraint("uq_accounts_code", "accounts", ["code"])
    op.add_column("accounts", sa.Column("currency", sa.String(3), nullable=True))
    op.add_column(
        "accounts",
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )

    # ================================================================
    # transactions: drop redundant amount; add status, posted_at, metadata
    # ================================================================
    op.drop_column("transactions", "amount")
    op.execute("CREATE TYPE transactionstatus AS ENUM ('PENDING', 'POSTED', 'VOIDED')")
    op.add_column(
        "transactions",
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "POSTED",
                "VOIDED",
                name="transactionstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="POSTED",
        ),
    )
    op.add_column("transactions", sa.Column("posted_at", sa.DateTime(), nullable=True))
    op.add_column("transactions", sa.Column("metadata", sa.JSON(), nullable=True))

    # ================================================================
    # entries: rename enum type, rename column, BIGINT amount, add currency, FK RESTRICT
    # ================================================================
    op.execute("ALTER TYPE entrytype RENAME TO direction")
    op.alter_column("entries", "entry_type", new_column_name="direction")
    op.alter_column(
        "entries",
        "amount",
        existing_type=sa.Numeric(precision=18, scale=4),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="(amount * 100)::bigint",
    )
    op.add_column("entries", sa.Column("currency", sa.String(3), nullable=True))
    op.drop_constraint("entries_transaction_id_fkey", "entries", type_="foreignkey")
    op.create_foreign_key(
        "entries_transaction_id_fkey",
        "entries",
        "transactions",
        ["transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # entries
    op.drop_constraint("entries_transaction_id_fkey", "entries", type_="foreignkey")
    op.create_foreign_key(
        "entries_transaction_id_fkey",
        "entries",
        "transactions",
        ["transaction_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("entries", "currency")
    op.alter_column(
        "entries",
        "amount",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(precision=18, scale=4),
        existing_nullable=False,
        postgresql_using="amount::numeric / 100",
    )
    op.alter_column("entries", "direction", new_column_name="entry_type")
    op.execute("ALTER TYPE direction RENAME TO entrytype")

    # transactions
    op.drop_column("transactions", "metadata")
    op.drop_column("transactions", "posted_at")
    op.drop_column("transactions", "status")
    op.execute("DROP TYPE transactionstatus")
    op.add_column(
        "transactions",
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="0",
        ),
    )

    # accounts
    op.drop_column("accounts", "updated_at")
    op.drop_column("accounts", "is_active")
    op.drop_column("accounts", "currency")
    op.drop_constraint("uq_accounts_code", "accounts", type_="unique")
    op.drop_column("accounts", "code")
