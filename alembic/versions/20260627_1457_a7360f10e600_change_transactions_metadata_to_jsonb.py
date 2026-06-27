"""change_transactions_metadata_to_jsonb

Revision ID: a7360f10e600
Revises: dba49c02eafb
Create Date: 2026-06-27 14:57:05.091210

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7360f10e600"
down_revision: Union[str, None] = "dba49c02eafb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN metadata TYPE JSONB USING metadata::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN metadata TYPE JSON USING metadata::text"
    )
