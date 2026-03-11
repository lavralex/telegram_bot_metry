"""Add dedicated Bitrix OAuth tokens table

Revision ID: a1f4c8d2b7e3
Revises: 9f1c2a7d4b10
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1f4c8d2b7e3"
down_revision: Union[str, Sequence[str], None] = "9f1c2a7d4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bitrix_oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portal", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portal", name="uq_bitrix_oauth_tokens_portal"),
    )
    op.create_index("ix_bitrix_oauth_tokens_id", "bitrix_oauth_tokens", ["id"], unique=False)
    op.create_index("ix_bitrix_oauth_tokens_portal", "bitrix_oauth_tokens", ["portal"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_bitrix_oauth_tokens_portal", table_name="bitrix_oauth_tokens")
    op.drop_index("ix_bitrix_oauth_tokens_id", table_name="bitrix_oauth_tokens")
    op.drop_table("bitrix_oauth_tokens")
