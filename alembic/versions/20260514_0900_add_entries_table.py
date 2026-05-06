"""add entries table with double-entry check constraint

Revision ID: a1b2c3d4e5f6
Revises: 3b594199520d
Create Date: 2026-05-14 09:00:00.000000

💡 Design notes (for interview):
- entries.amount > 0 is a row-level guard (no zero or negative amounts).
- The transaction-level balance rule (SUM(debit) == SUM(credit)) cannot be
  expressed as a simple PostgreSQL CHECK on the entries table because CHECK
  constraints cannot reference aggregate functions across rows.
- The canonical PostgreSQL solution is a CONSTRAINT TRIGGER or
  application-layer enforcement. Here we add a COMMENT on the transactions
  table to document the invariant, and rely on the service layer + integration
  tests to enforce it. See S1-3 / S1-4 for service-layer enforcement.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "3b594199520d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create entries table
    op.create_table(
        "entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum("debit", "credit", name="entrytype"),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        # ✅ DONE条件: Row-level CHECK — amount must be positive
        sa.CheckConstraint("amount > 0", name="ck_entries_amount_positive"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_entries_transaction_id", "entries", ["transaction_id"]
    )
    op.create_index(
        "ix_entries_account_id", "entries", ["account_id"]
    )

    # TODO: CONSTRAINT TRIGGERによる借方=貸方の合計チェックはS1-3以降で実装
    #       ここではテーブル構造とインデックスのみ確立する
    # Add documentation comment on transactions table
    op.execute(
        "COMMENT ON TABLE transactions IS "
        "'Header for a double-entry transaction. "
        "Invariant: SUM(entries.amount WHERE entry_type=debit) "
        "= SUM(entries.amount WHERE entry_type=credit). "
        "Enforced by service layer and integration tests.'"
    )


def downgrade() -> None:
    op.drop_index("ix_entries_account_id", table_name="entries")
    op.drop_index("ix_entries_transaction_id", table_name="entries")
    op.drop_table("entries")
    op.execute("DROP TYPE IF EXISTS entrytype")
