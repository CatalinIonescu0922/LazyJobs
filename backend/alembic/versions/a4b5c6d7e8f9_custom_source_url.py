"""add custom source URL

Revision ID: a4b5c6d7e8f9
Revises: 9e3f4a5b6c7d
Create Date: 2026-11-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "9e3f4a5b6c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("source_url", sa.String(length=1024), nullable=False, server_default=""))
    op.alter_column("job_sources", "source_url", server_default=None)


def downgrade() -> None:
    op.drop_column("job_sources", "source_url")