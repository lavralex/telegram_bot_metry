import logging
from typing import Callable, Dict, Any, Awaitable, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from sqlalchemy import desc

from app.core.config import config
from app.core.database import SessionLocal
from app.core.dependencies import get_user_repository

from app.application.services.lead_service import LeadService
from app.application.repositories.lead_repository import LeadRepository
from app.application.repositories.message_repository import MessageRepository

from app.infrastructure.database.models import Lead
from app.infrastructure.external.bitrix24 import ensure_bitrix_lead, send_message_to_openlines

logger = logging.getLogger("bot.messages")


class UserMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        if not event.message:
            return await handler(event, data)

        message: Message = event.message

        if message.chat.type != "private":
            return await handler(event, data)

        user_id = message.from_user.id

        if message.text and message.text.startswith("/"):
            return await handler(event, data)

        if user_id in config.ADMIN_IDS:
            return await handler(event, data)

        if not (message.text or message.caption or message.photo or message.document):
            return await handler(event, data)

        incoming_preview = (message.text or message.caption or "")
        logger.info("🔥 Middleware fired: user_id=%s text=%r", user_id, incoming_preview[:120])

        state_data: Dict[str, Any] = {}
        state = data.get("state")
        if state:
            try:
                state_data = await state.get_data()
            except Exception:
                state_data = {}

        user_repo = get_user_repository()
        try:
            utm_source = (state_data.get("utm_source") or "organic")
            user_repo.get_or_create_user(
                {
                    "user_id": user_id,
                    "username": message.from_user.username,
                    "first_name": message.from_user.first_name,
                    "last_name": message.from_user.last_name,
                },
                utm_source,
            )
            user_repo.update_user_activity(user_id)
        except Exception as e:
            logger.error("❌ Ошибка трекинга пользователя: %s", e, exc_info=True)
        finally:
            try:
                user_repo.db.close()
            except Exception:
                pass

        user_data = {
            "user_id": user_id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
        }

        db = SessionLocal()
        ol_sent_ok = False
        ol_error: Optional[str] = None

        try:
            msg_repo = MessageRepository(db)
            lead_repo = LeadRepository(db)
            lead_service = LeadService(lead_repo)

            lead: Optional[Lead] = (
                db.query(Lead)
                .filter(Lead.user_id == user_id)
                .order_by(desc(Lead.created_at))
                .first()
            )

            if lead:
                logger.info(
                    "ℹ️ Found existing lead: lead_id=%s bitrix_lead_id=%s utm=%s",
                    lead.id,
                    getattr(lead, "bitrix_lead_id", None),
                    getattr(lead, "utm_source", None),
                )

            message_text = message.text or message.caption or ""
            if not message_text and (message.photo or message.document):
                message_text = "[media]"

            if not lead:
                lead, bitrix_fields = lead_service.create_minimal_lead_from_state(user_data, state_data)
                logger.info("✅ Minimal lead created in DB: lead_id=%s", lead.id)
            else:
                lead_repo.update_lead_from_state(lead.id, state_data)
                _, bitrix_fields = lead_service.create_minimal_lead_from_state(user_data, state_data)

            if config.BITRIX24_ENABLED:
                bres = await ensure_bitrix_lead(lead, bitrix_fields)
                if bres.get("success"):
                    ensured_id = int(bres["lead_id"])
                    if not getattr(lead, "bitrix_lead_id", None):
                        try:
                            lead_repo.set_bitrix_lead_id(lead.id, ensured_id)
                            lead.bitrix_lead_id = ensured_id
                        except Exception as e:
                            logger.warning("⚠️ Не удалось сохранить bitrix_lead_id=%s: %s", ensured_id, e)
                    logger.info("✅ Bitrix lead ensured: %s (created=%s)", ensured_id, bres.get("created"))
                else:
                    logger.warning("⚠️ Bitrix lead ensure failed: %s", bres.get("error"))

            utm_to_use = (
                getattr(lead, "utm_source", None)
                or state_data.get("utm_source")
                or "organic"
            )

            message_data = {
                "user_id": user_id,
                "message_text": message_text,
                "direction": "user_to_admin",
                "utm_source": utm_to_use,
                "lead_id": lead.id if lead else None,
            }
            if message.photo:
                message_data["photo_url"] = message.photo[-1].file_id
            if message.document:
                message_data["document_url"] = message.document.file_id

            msg_repo.create_message(message_data)
            logger.info("💾 Message saved: user_id=%s utm=%s lead_id=%s", user_id, utm_to_use, message_data["lead_id"])

            if config.BITRIX24_ENABLED and getattr(config, "BITRIX24_OPENLINES_ENABLED", True):
                bitrix_lead_id = getattr(lead, "bitrix_lead_id", None)
                if not bitrix_lead_id:
                    logger.warning("⚠️ No bitrix_lead_id for lead_id=%s, sending to OL anyway", lead.id)

                seg = state_data.get("segment") or getattr(lead, "segment", None) or "unknown"
                utm = state_data.get("utm_source") or getattr(lead, "utm_source", None) or "organic"
                prefix = f"[segment={seg}, utm={utm}] "

                ol_res = await send_message_to_openlines(
                    lead_id=int(bitrix_lead_id) if bitrix_lead_id else 0,
                    tg_user_id=user_id,
                    tg_username=message.from_user.username or "",
                    text=prefix + message_text,
                    message_id=str(message.message_id),
                    unix_date=int(message.date.timestamp()),
                )

                if not ol_res.get("success"):
                    ol_error = str(ol_res.get("error") or ol_res.get("raw") or "unknown error")
                    logger.warning("⚠️ OpenLines send failed: %s", ol_error)
                else:
                    ol_sent_ok = True
                    logger.info("✅ OpenLines send OK")

        except Exception as e:
            ol_error = str(e)
            logger.error("❌ Ошибка middleware: %s", e, exc_info=True)
        finally:
            try:
                db.close()
            except Exception:
                pass

        try:
            if config.BITRIX24_ENABLED and getattr(config, "BITRIX24_OPENLINES_ENABLED", True):
                if ol_sent_ok:
                    await message.answer("✅ Сообщение отправлено менеджеру. Он ответит здесь.")
                else:
                    await message.answer("⚠️ Не удалось отправить менеджеру. Попробуйте ещё раз чуть позже.")
        except Exception as e:
            logger.warning("Не смогли отправить ACK пользователю: %s", e)

        return await handler(event, data)
