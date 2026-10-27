"""add profile location and salary currency

Revision ID: 7c4f1b8e2d9a
Revises: 2f708cf4a9ef
Create Date: 2026-10-27 21:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c4f1b8e2d9a"
down_revision: Union[str, Sequence[str], None] = "2f708cf4a9ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("country", sa.String(length=2), nullable=False, server_default=""))
    op.add_column("profiles", sa.Column("city", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("profiles", sa.Column("salary_currency", sa.String(length=3), nullable=False, server_default=""))
    op.alter_column("profiles", "country", server_default=None)
    op.alter_column("profiles", "city", server_default=None)
    op.alter_column("profiles", "salary_currency", server_default=None)


def downgrade() -> None:
    op.drop_column("profiles", "salary_currency")
    op.drop_column("profiles", "city")
    op.drop_column("profiles", "country")