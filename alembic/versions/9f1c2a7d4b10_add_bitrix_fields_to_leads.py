"""Add Bitrix lead id and OpenLines chat id to leads; make segment nullable

Revision ID: 9f1c2a7d4b10
Revises: eed6d03fc4d9
Create Date: 2026-02-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f1c2a7d4b10"
down_revision: Union[str, Sequence[str], None] = "eed6d03fc4d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Добавляем bitrix_lead_id
    op.add_column("leads", sa.Column("bitrix_lead_id", sa.Integer(), nullable=True))
    op.create_index("ix_leads_bitrix_lead_id", "leads", ["bitrix_lead_id"], unique=False)

    # 2) Добавляем openlines_chat_id (опционально, но полезно)
    op.add_column("leads", sa.Column("openlines_chat_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_leads_openlines_chat_id", "leads", ["openlines_chat_id"], unique=False)

    # 3) Делаем segment nullable (по новой логике “минимальный лид”)
    # было nullable=False -> станет nullable=True
    op.alter_column(
        "leads",
        "segment",
        existing_type=sa.String(length=50),
        nullable=True,
    )

    # 4) (необязательно) индекс по user_id уже может быть, но если нет — полезно
    # Поскольку ты создавал модель без явного Index, на PG индекс мог не появиться.
    # Безопасно: сначала попробуем создать в try/except через DO block нельзя в alembic прямо,
    # поэтому оставим как опциональный кусок. Если хочешь — включим после проверки.
    #
    # op.create_index("ix_leads_user_id", "leads", ["user_id"], unique=False)


def downgrade() -> None:
    # 1) Вернем segment обратно в NOT NULL
    op.alter_column(
        "leads",
        "segment",
        existing_type=sa.String(length=50),
        nullable=False,
    )

    # 2) Удалим openlines_chat_id
    op.drop_index("ix_leads_openlines_chat_id", table_name="leads")
    op.drop_column("leads", "openlines_chat_id")

    # 3) Удалим bitrix_lead_id
    op.drop_index("ix_leads_bitrix_lead_id", table_name="leads")
    op.drop_column("leads", "bitrix_lead_id")
