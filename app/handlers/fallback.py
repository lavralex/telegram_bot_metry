from __future__ import annotations

import logging
import time

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.core.dependencies import get_lead_repository
from app.application.services.lead_service import LeadService
from app.infrastructure.external.bitrix24 import ensure_bitrix_lead, send_message_to_openlines

logger = logging.getLogger(__name__)
fallback_router = Router()


def _tg_user_info(message: Message) -> dict:
    u = message.from_user
    return {
        "user_id": u.id,
        "username": u.username or "",
        "first_name": u.first_name or "",
        "last_name": u.last_name or "",
    }


@fallback_router.message(F.chat.type == "private")
async def fallback_private(message: Message, state: FSMContext):
    """
    Любое личное сообщение (кроме команд):
    - ensure локальный лид (не плодим)
    - ensure Bitrix lead (OAuth/webhook в зависимости от конфига)
    - отправляем сообщение в OpenLines с привязкой к lead
    """
    if message.text and message.text.startswith("/"):
        return

    text = message.text or ""
    tg_user_id = message.from_user.id
    tg_username = message.from_user.username or ""

    logger.info("📩 Fallback handler: user_id=%s text=%r", tg_user_id, text[:120])

    state_data = await state.get_data()
    lead_repo = get_lead_repository()
    try:
        lead_service = LeadService(lead_repo)
        lead_obj, bitrix_fields = lead_service.ensure_minimal_lead_from_state(_tg_user_info(message), state_data)
        ensured_bitrix_id = getattr(lead_obj, "bitrix_lead_id", None)

        if config.BITRIX24_ENABLED:
            bres = await ensure_bitrix_lead(lead_obj, bitrix_fields)
            if bres.get("success"):
                ensured_bitrix_id = int(bres["lead_id"])
                if not getattr(lead_obj, "bitrix_lead_id", None):
                    lead_repo.set_bitrix_lead_id(lead_obj.id, ensured_bitrix_id)
                    lead_obj.bitrix_lead_id = ensured_bitrix_id
            else:
                logger.warning("⚠️ Bitrix lead ensure failed: %s", bres)
                await message.answer(
                    "Я принял сообщение ✅\n"
                    "Но сейчас CRM недоступна. Менеджер всё равно увидит ваше обращение."
                )
                return

        if config.BITRIX24_ENABLED and getattr(config, "BITRIX24_OPENLINES_ENABLED", True):
            lead_id_for_ol = int(ensured_bitrix_id) if ensured_bitrix_id else 0

            res = await send_message_to_openlines(
                lead_id=lead_id_for_ol,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                text=text,
                message_id=str(message.message_id),
                unix_date=int(time.time()),
            )

            if not res.get("success"):
                logger.warning("⚠️ OpenLines send failed: %s", res)

        await message.answer(
            "Я передал ваше сообщение менеджеру.\n"
            "Он ответит вам прямо здесь 💬"
        )

    finally:
        try:
            lead_repo.db.close()
        except Exception:
            pass
