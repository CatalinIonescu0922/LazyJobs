"""normalize job URLs

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM jobs duplicate
        USING jobs keeper
        WHERE duplicate.id > keeper.id
          AND duplicate.source = keeper.source
          AND split_part(duplicate.external_id, '#', 1) = split_part(keeper.external_id, '#', 1)
        """
    )
    op.execute("UPDATE jobs SET external_id = split_part(external_id, '#', 1), url = split_part(url, '#', 1)")


def downgrade() -> None:
    pass