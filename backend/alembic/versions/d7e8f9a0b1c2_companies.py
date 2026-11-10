"""add the companies table

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("postings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unchecked"),
        sa.Column("ats_provider", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("ats_slug", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key", name="uq_user_company_key"),
    )
    op.create_index("ix_companies_user_id", "companies", ["user_id"])
    op.create_index("ix_companies_status", "companies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_companies_status", table_name="companies")
    op.drop_index("ix_companies_user_id", table_name="companies")
    op.drop_table("companies")
