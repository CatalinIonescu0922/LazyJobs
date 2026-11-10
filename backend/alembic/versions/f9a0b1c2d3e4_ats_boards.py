"""add the directory of ATS boards and the board matched to a company

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ats_boards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("token_key", sa.String(length=255), nullable=False),
        sa.Column("open_roles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "token", name="uq_ats_board_provider_token"),
    )
    op.create_index("ix_ats_boards_key", "ats_boards", ["key"])
    op.create_index("ix_ats_boards_token_key", "ats_boards", ["token_key"])
    op.add_column("companies", sa.Column("board_provider", sa.String(length=32), nullable=True))
    op.add_column("companies", sa.Column("board_token", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "board_token")
    op.drop_column("companies", "board_provider")
    op.drop_index("ix_ats_boards_token_key", table_name="ats_boards")
    op.drop_index("ix_ats_boards_key", table_name="ats_boards")
    op.drop_table("ats_boards")
