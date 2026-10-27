"""add job sources and crawler fields

Revision ID: 8d2f3c4b5a6e
Revises: 7c4f1b8e2d9a
Create Date: 2026-10-27 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8d2f3c4b5a6e"
down_revision: Union[str, Sequence[str], None] = "7c4f1b8e2d9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jobs", "source", existing_type=sa.String(length=32), type_=sa.String(length=255))
    op.alter_column("jobs", "external_id", existing_type=sa.String(length=255), type_=sa.String(length=1024))
    op.add_column("jobs", sa.Column("eligible_countries", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("jobs", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(length=3), nullable=False, server_default=""))
    op.add_column("jobs", sa.Column("fingerprint", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("jobs", sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_jobs_fingerprint", "jobs", ["fingerprint"], unique=False)
    op.alter_column("jobs", "eligible_countries", server_default=None)
    op.alter_column("jobs", "salary_currency", server_default=None)
    op.alter_column("jobs", "fingerprint", server_default=None)
    op.alter_column("jobs", "first_seen_at", server_default=None)

    op.create_table(
        "job_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("extraction", sa.String(length=32), nullable=False),
        sa.Column("sitemap_url", sa.String(length=1024), nullable=False),
        sa.Column("posting_prefix", sa.String(length=1024), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("posting_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "domain", name="uq_user_job_source_kind_domain"),
    )
    op.create_index("ix_job_sources_user_id", "job_sources", ["user_id"], unique=False)
    op.create_index("ix_job_sources_status", "job_sources", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_sources_status", table_name="job_sources")
    op.drop_index("ix_job_sources_user_id", table_name="job_sources")
    op.drop_table("job_sources")
    op.drop_index("ix_jobs_fingerprint", table_name="jobs")
    op.drop_column("jobs", "first_seen_at")
    op.drop_column("jobs", "fingerprint")
    op.drop_column("jobs", "salary_currency")
    op.drop_column("jobs", "salary_max")
    op.drop_column("jobs", "salary_min")
    op.drop_column("jobs", "expires_at")
    op.drop_column("jobs", "eligible_countries")
    op.alter_column("jobs", "external_id", existing_type=sa.String(length=1024), type_=sa.String(length=255))
    op.alter_column("jobs", "source", existing_type=sa.String(length=255), type_=sa.String(length=32))
