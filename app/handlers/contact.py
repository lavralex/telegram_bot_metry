from __future__ import annotations

import logging
from typing import Dict, Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from sqlalchemy import desc

from app.core.config import config
from app.core.dependencies import get_lead_repository, get_user_repository
from app.application.services.lead_service import LeadService
from app.keyboards.contact import get_subscribe_keyboard

from app.infrastructure.database.models import Lead
from app.infrastructure.external.bitrix24 import (
    ensure_bitrix_lead,
    send_message_to_openlines,
    enrich_openlines_lead,
    enrich_openlines_lead_by_id,
    enrich_openlines_lead_by_phone,
)

logger = logging.getLogger(__name__)

contact_router = Router()


async def share_contact(message_or_callback, state: FSMContext):
    """Универсальная функция для запроса контакта"""
    data = await state.get_data()
    segment = data.get("segment", "unknown")
    experience = data.get("experience", "")

    show_new_auth_message = False
    if segment in ["investment", "living"]:
        show_new_auth_message = True
    elif segment == "manager" and experience != "уже инвестировал(а)":
        show_new_auth_message = True

    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    if show_new_auth_message:
        auth_message = "Пройдите авторизацию, и персональный менеджер вышлет каталог объектов с доходностью от 40%"
    else:
        auth_message = (
            "Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\n"
            "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков"
        )

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(auth_message, reply_markup=reply_keyboard)
    else:
        await message_or_callback.answer(auth_message, reply_markup=reply_keyboard)

    await state.set_state("waiting_for_phone_contact")


@contact_router.callback_query(F.data == "share_contact")
async def share_contact_handler(callback: CallbackQuery, state: FSMContext):
    await share_contact(callback, state)
    await callback.answer()


def build_bitrix_fields_from_lead(lead: Lead) -> Dict[str, Any]:
    """
    Собираем поля для Bitrix из уже существующего/обновлённого lead в нашей БД.
    ВАЖНО: НЕ создаёт новый lead.
    """
    segment = (getattr(lead, "segment", None) or "").strip() or None
    utm_source = (getattr(lead, "utm_source", None) or "").strip() or "organic"
    phone_v = (getattr(lead, "phone", None) or "").strip() or None

    budget = (getattr(lead, "budget", None) or "").strip() or None
    timeline = (getattr(lead, "timeline", None) or "").strip() or None
    management = (getattr(lead, "management", None) or "").strip() or None
    experience = (getattr(lead, "experience", None) or "").strip() or None
    user_path = getattr(lead, "user_path", None) or []

    username = getattr(lead, "username", None) or ""
    first_name = getattr(lead, "first_name", None) or ""
    last_name = getattr(lead, "last_name", None) or ""

    parts = []
    if segment:
        parts.append(f"Сегмент: {segment}")
    if utm_source:
        parts.append(f"UTM: {utm_source}")
    if budget:
        parts.append(f"Бюджет: {budget}")
    if timeline:
        parts.append(f"Срок: {timeline}")
    if management:
        parts.append(f"Управление: {management}")
    if experience:
        parts.append(f"Опыт: {experience}")
    if user_path:
        parts.append(f"Путь: {' → '.join(map(str, user_path))}")

    comments = "\n".join(parts) if parts else "Лид из Telegram."

    title_user = f"@{username}" if username else f"tg:{lead.user_id}"
    title_seg = segment if segment else "без сегмента"

    fields: Dict[str, Any] = {
        "TITLE": f"Telegram {title_user} — {title_seg}",
        "NAME": first_name or (username if username else ""),
        "LAST_NAME": last_name or "",
        "COMMENTS": comments,
    }

    if phone_v:
        fields["PHONE"] = [{"VALUE": phone_v, "VALUE_TYPE": "WORK"}]

    return fields


async def process_contact_all(message: Message, state: FSMContext):
    if not message.contact:
        return

    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    user_data = await state.get_data()
    user_repo = get_user_repository()
    lead_repo = get_lead_repository()
    lead_service = LeadService(lead_repo)
    user_info = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name,
    }

    lead_obj: Lead | None = None
    bitrix_fields: Dict[str, Any] = {}

    try:
        user_repo.mark_contact_shared(message.from_user.id, phone)
        
        lead_obj, _ = lead_service.create_new_lead_from_state(user_info, user_data)
        logger.info("✅ (CONTACT) Новый лид создан в БД с ID: %s", lead_obj.id)

        bitrix_fields = build_bitrix_fields_from_lead(lead_obj)
        user_repo.mark_lead_created(message.from_user.id)


    except Exception as e:
        logger.error("❌ Ошибка обработки контакта: %s", e, exc_info=True)
        await message.answer("Произошла ошибка при сохранении данных. Попробуйте позже.")
        return

    finally:
        try:
            user_repo.db.close()
        except Exception:
            pass
    ensured_bitrix_id = getattr(lead_obj, "bitrix_lead_id", None)
    ol_owns_lead = bool(getattr(config, "BITRIX24_OPENLINES_OWNS_LEAD", False))

    if config.BITRIX24_ENABLED and not ol_owns_lead:
        try:
            bres = await ensure_bitrix_lead(lead_obj, bitrix_fields)
            if bres.get("success"):
                ensured_bitrix_id = int(bres["lead_id"])
                logger.info("✅ Bitrix lead ensured: %s (created=%s)", ensured_bitrix_id, bres.get("created"))

                if not getattr(lead_obj, "bitrix_lead_id", None):
                    try:
                        lead_repo2 = get_lead_repository()
                        try:
                            lead_repo2.set_bitrix_lead_id(lead_obj.id, ensured_bitrix_id)
                        finally:
                            lead_repo2.db.close()
                        lead_obj.bitrix_lead_id = ensured_bitrix_id
                    except Exception as e:
                        logger.warning("⚠️ Не удалось сохранить bitrix_lead_id в БД: %s", e)
            else:
                logger.warning("⚠️ Bitrix lead ensure failed: %s", bres.get("error"))
        except Exception as e:
            logger.error("⚠️ Ошибка при работе с Bitrix24: %s", e, exc_info=True)

    if config.BITRIX24_ENABLED and getattr(config, "BITRIX24_OPENLINES_ENABLED", True):
        try:
            lead_id_for_ol = int(ensured_bitrix_id) if ensured_bitrix_id else 0
            if ol_owns_lead:
                # In OL-owned mode route strictly by chat token to avoid sticking to stale CRM lead id.
                lead_id_for_ol = 0
            seg = user_data.get("segment") or getattr(lead_obj, "segment", None) or "unknown"
            utm = user_data.get("utm_source") or getattr(lead_obj, "utm_source", None) or "organic"
            prefix = f"[segment={seg}, utm={utm}] "

            if lead_id_for_ol <= 0 and not ol_owns_lead:
                logger.warning("⚠️ Skip OpenLines send: missing bitrix_lead_id for local lead_id=%s", getattr(lead_obj, "id", None))
            else:
                ol_res = await send_message_to_openlines(
                    lead_id=lead_id_for_ol,
                    tg_user_id=message.from_user.id,
                    tg_username=message.from_user.username or "",
                    text=prefix + f"📞 Пользователь оставил телефон: {phone}",
                    message_id=f"contact_{message.message_id}",
                    unix_date=int(message.date.timestamp()),
                    attach_crm=lead_id_for_ol > 0,
                    chat_token=(f"lead_{getattr(lead_obj, 'id', 0)}" if ol_owns_lead else ""),
                )
                if lead_id_for_ol <= 0 and ol_res.get("success"):
                    enrich: Dict[str, Any] = {"success": False, "error": "NO_LEAD_ID_OR_CHAT_ID"}
                    ol_lead_id = int(ol_res.get("ol_lead_id") or 0)
                    if ol_lead_id > 0:
                        enrich = await enrich_openlines_lead_by_id(
                            lead_id=ol_lead_id,
                            fields=bitrix_fields,
                            trace_id=f"contact_{message.message_id}",
                        )
                    else:
                        lookup_chat_id = str(ol_res.get("im_chat_id") or ol_res.get("connector_chat_id") or "")
                        if lookup_chat_id:
                            enrich = await enrich_openlines_lead(
                                im_chat_id=lookup_chat_id,
                                fields=bitrix_fields,
                                trace_id=f"contact_{message.message_id}",
                            )

                    if enrich.get("success"):
                        ensured_bitrix_id = int(enrich["lead_id"])
                        lead_repo3 = get_lead_repository()
                        try:
                            lead_repo3.set_bitrix_lead_id(lead_obj.id, ensured_bitrix_id)
                        finally:
                            lead_repo3.db.close()
                        lead_obj.bitrix_lead_id = ensured_bitrix_id
                        logger.info("✅ OpenLines lead enriched: %s", ensured_bitrix_id)
                    else:
                        if phone:
                            by_phone = await enrich_openlines_lead_by_phone(
                                phone=phone,
                                fields=bitrix_fields,
                                trace_id=f"contact_{message.message_id}P",
                            )
                            if by_phone.get("success"):
                                ensured_bitrix_id = int(by_phone["lead_id"])
                                lead_repo3 = get_lead_repository()
                                try:
                                    lead_repo3.set_bitrix_lead_id(lead_obj.id, ensured_bitrix_id)
                                finally:
                                    lead_repo3.db.close()
                                lead_obj.bitrix_lead_id = ensured_bitrix_id
                                logger.info("OpenLines lead enriched by phone: %s", ensured_bitrix_id)
                            else:
                                logger.warning("OpenLines lead enrich failed: %s", enrich)
                                logger.warning("OpenLines lead enrich by phone failed: %s", by_phone)
                        else:
                            logger.warning("OpenLines lead enrich failed: %s", enrich)
        except Exception as e:
            logger.warning("⚠️ Не удалось отправить сообщение в OpenLines: %s", e)

    try:
        await print_lead_info(user_info, user_data, getattr(lead_obj, "id", 0) or 0)
    except Exception:
        pass

    try:
        await message.answer("Спасибо! ✅", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass

    segment = user_data.get("segment", "unknown")
    experience = user_data.get("experience", "")
    await send_final_messages(message, segment, experience)

    try:
        lead_repo.db.close()
    except Exception:
        pass

    await state.clear()


@contact_router.message(F.contact, F.state == "waiting_for_phone_contact")
async def process_contact_with_state(message: Message, state: FSMContext):
    await process_contact_all(message, state)


@contact_router.message(F.contact)
async def process_contact_any_state(message: Message, state: FSMContext):
    """
    Fallback contact handler: some clients/flows may send contact outside the expected FSM state.
    We still treat it as an authorization contact and create a new lead.
    """
    await process_contact_all(message, state)


async def print_lead_info(user_info: dict, user_data: dict, lead_id: int):
    """Выводит информацию о лиде в консоль"""
    segment = user_data.get("segment", "unknown")
    utm_source = user_data.get("utm_source", "organic")
    user_path = user_data.get("user_path", [])
    phone = user_data.get("phone", "не указан")

    traffic_source = "органический"
    if utm_source != "organic":
        for utm_key, utm_name in config.UTM_SEGMENTS.items():
            if utm_key == utm_source:
                traffic_source = f"UTM ({utm_name})"
                break
        else:
            traffic_source = f"UTM ({utm_source})"

    user_journey = " → ".join(user_path)

    logger.info(
        f"""
НОВЫЙ ЛИД / КОНТАКТ ПОЛУЧЕН
📋 ID лида: {lead_id}
📊 Сегмент: {segment}
🔗 Источник трафика: {traffic_source}
🏷️ UTM метка: {utm_source}
📞 Телефон: {phone}
🛣️ Путь пользователя: {user_journey}
👤 User ID: {user_info.get('user_id')}
"""
    )


async def send_final_messages(message: Message, segment: str, experience: str):
    """Отправляет финальные сообщения в зависимости от сегмента"""
    if segment == "analytics":
        try:
            pdf_file = FSInputFile(config.analytics_pdf_path)
            await message.answer_document(
                document=pdf_file,
                caption=(
                    "Благодарим! Делимся с вами доходностью локаций.\n"
                    "Данные аналитики относятся только к объектам под нашим управлением"
                ),
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки PDF: {e}")
            await message.answer(
                "К сожалению, файл аналитики временно недоступен.\n"
                "Наш менеджер свяжется с вами и отправит актуальные данные."
            )

        await send_subscribe_message(message)

    elif segment == "manager":
        if experience == "уже инвестировал(а)":
            await message.answer("Отлично! Персональный менеджер скоро свяжется с Вами!")
            await send_subscribe_message(message)
        else:
            try:
                investor_portfolio_file = FSInputFile(config.investor_portfolio_path)
                await message.answer_document(
                    document=investor_portfolio_file,
                    caption=(
                        "Благодарим! Ваш персональный менеджер скоро свяжется с вами. "
                        "А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки PDF портфеля инвестора: {e}")
                await message.answer(
                    "Благодарим! Ваш персональный менеджер скоро свяжется с вами. "
                    "А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>",
                    parse_mode="HTML",
                )
            await send_subscribe_message(message)

    elif segment in ["investment", "living"]:
        try:
            investor_portfolio_file = FSInputFile(config.investor_portfolio_path)
            await message.answer_document(
                document=investor_portfolio_file,
                caption=(
                    "Благодарим! Ваш персональный менеджер скоро свяжется с вами. "
                    "А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки PDF портфеля инвестора: {e}")
            await message.answer("Благодарим! Ваш персональный менеджер скоро свяжется с вами.", parse_mode="HTML")
        await send_subscribe_message(message)

    else:
        await message.answer("Благодарим! Ваш персональный менеджер скоро свяжется с вами.")
        await send_subscribe_message(message)


async def send_subscribe_message(message: Message):
    """Отправляет сообщение с картинкой подписки"""
    try:
        subscribe_img = FSInputFile(config.subscribe_image_path)
        await message.answer_photo(photo=subscribe_img, caption="", reply_markup=get_subscribe_keyboard())
    except Exception as e:
        logger.error(f"❌ Ошибка отправки картинки подписки: {e}")
        await message.answer("Узнавайте первыми о новых объектах недвижимости!", reply_markup=get_subscribe_keyboard())

