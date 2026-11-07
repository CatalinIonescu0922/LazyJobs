"""add job work mode

Revision ID: 9e3f4a5b6c7d
Revises: 8d2f3c4b5a6e
Create Date: 2026-11-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9e3f4a5b6c7d"
down_revision: Union[str, Sequence[str], None] = "8d2f3c4b5a6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("work_mode", sa.String(length=16), nullable=False, server_default="unknown"))
    op.execute("UPDATE jobs SET work_mode = CASE WHEN remote THEN 'remote' ELSE 'onsite' END")
    op.alter_column("jobs", "work_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "work_mode")