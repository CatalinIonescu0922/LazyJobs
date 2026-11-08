"""add ATS feed identifiers to job sources

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-11-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("ats_provider", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("job_sources", sa.Column("ats_slug", sa.String(length=255), nullable=False, server_default=""))
    op.alter_column("job_sources", "ats_provider", server_default=None)
    op.alter_column("job_sources", "ats_slug", server_default=None)


def downgrade() -> None:
    op.drop_column("job_sources", "ats_slug")
    op.drop_column("job_sources", "ats_provider")
