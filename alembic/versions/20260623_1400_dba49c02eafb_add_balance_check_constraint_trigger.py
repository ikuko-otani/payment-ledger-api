"""add_balance_check_constraint_trigger

Revision ID: dba49c02eafb
Revises: d117489c7a4b
Create Date: 2026-06-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dba49c02eafb"
down_revision: Union[str, None] = "d117489c7a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION check_entries_balance()
        RETURNS TRIGGER AS $$
        DECLARE
            debit_sum  BIGINT;
            credit_sum BIGINT;
        BEGIN
            SELECT
                COALESCE(SUM(amount) FILTER (WHERE direction = 'DEBIT'),  0),
                COALESCE(SUM(amount) FILTER (WHERE direction = 'CREDIT'), 0)
            INTO debit_sum, credit_sum
            FROM entries
            WHERE transaction_id = NEW.transaction_id;

            IF debit_sum <> credit_sum THEN
                RAISE EXCEPTION
                    'entries are not balanced: debit=% credit=%',
                    debit_sum, credit_sum
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_check_entries_balance
        AFTER INSERT ON entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION check_entries_balance();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_entries_balance ON entries;")
    op.execute("DROP FUNCTION IF EXISTS check_entries_balance();")
