from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.core.dependencies import get_lead_repository, get_user_repository
from app.application.services.lead_service import LeadService
from app.keyboards.contact import get_subscribe_keyboard
from app.infrastructure.external.bitrix24 import create_bitrix_lead
import logging

logger = logging.getLogger(__name__)

contact_router = Router()

async def share_contact(message_or_callback, state: FSMContext):
    """Универсальная функция для запроса контакта"""
    data = await state.get_data()
    segment = data.get('segment', 'unknown')
    experience = data.get('experience', '')

    show_new_auth_message = False
    if segment in ["investment", "living"]:
        show_new_auth_message = True
    elif segment == "manager" and experience != "уже инвестировал(а)":
        show_new_auth_message = True
    
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    if show_new_auth_message:
        auth_message = "Пройдите авторизацию, и персональный менеджер вышлет каталог объектов с доходностью от 40%"
    else:
        auth_message = "Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\nВаши данные полностью защищены — обещаем, никаких навязчивых звонков"

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(auth_message, reply_markup=reply_keyboard)
    else:
        await message_or_callback.answer(auth_message, reply_markup=reply_keyboard)
    
    await state.set_state("waiting_for_phone_contact")

@contact_router.callback_query(F.data == "share_contact")
async def share_contact_handler(callback: CallbackQuery, state: FSMContext):
    await share_contact(callback, state)
    await callback.answer()

@contact_router.message(F.contact)
async def process_contact_all(message: Message, state: FSMContext):
    if not message.contact:
        return

    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    user_data = await state.get_data()

    user_repo = get_user_repository()
    user_repo.mark_contact_shared(message.from_user.id, phone)

    lead_repo = get_lead_repository()
    lead_service = LeadService(lead_repo)
    
    user_info = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }
    
    try:
        lead, bitrix_data = lead_service.create_lead_from_state(user_info, user_data)
        logger.info(f"✅ Лид сохранен в БД с ID: {lead.id}")

        user_repo.mark_lead_created(message.from_user.id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения лида: {e}")
        await message.answer("Произошла ошибка при сохранении данных. Попробуйте позже.")
        return

    if config.BITRIX24_ENABLED:
        try:
            bitrix_result = await create_bitrix_lead(bitrix_data)
            if bitrix_result['success']:
                logger.info(f"✅ Лид успешно создан в Bitrix24, ID: {bitrix_result['lead_id']}")
            else:
                logger.warning(f"⚠️ Ошибка создания лида в Bitrix24: {bitrix_result['error']}")
        except Exception as e:
            logger.error(f"⚠️ Ошибка при отправке в Bitrix24: {e}")

    await print_lead_info(user_info, user_data, lead.id)

    try:
        await message.edit_reply_markup(reply_markup=None)
    except:
        pass

    segment = user_data.get('segment', 'unknown')
    experience = user_data.get('experience', '')
    await send_final_messages(message, segment, experience)
    
    await state.clear()

@contact_router.message(F.contact, F.state == "waiting_for_phone_contact")
async def process_contact_with_state(message: Message, state: FSMContext):
    await process_contact_all(message, state)

async def print_lead_info(user_info: dict, user_data: dict, lead_id: int):
    """Выводит информацию о лиде в консоль"""
    segment = user_data.get('segment', 'unknown')
    utm_source = user_data.get('utm_source', 'organic')
    user_path = user_data.get('user_path', [])
    phone = user_data.get('phone', 'не указан')

    traffic_source = "органический"
    if utm_source != "organic":
        for utm_key, utm_name in config.UTM_SEGMENTS.items():
            if utm_key == utm_source:
                traffic_source = f"UTM ({utm_name})"
                break
        else:
            traffic_source = f"UTM ({utm_source})"

    user_journey = " → ".join(user_path)

    logger.info(f"""
НОВЫЙ ЛИД СОХРАНЕН В БАЗУ!
📋 ID лида: {lead_id}
📊 Сегмент: {segment}
🔗 Источник трафика: {traffic_source}
🏷️ UTM метка: {utm_source}
🛣️ Путь пользователя: {user_journey}
👤 User ID: {user_info.get('user_id')}
    """)

async def send_final_messages(message: Message, segment: str, experience: str):
    """Отправляет финальные сообщения в зависимости от сегмента"""
    if segment == "analytics":
        try:
            pdf_file = FSInputFile(config.analytics_pdf_path)
            await message.answer_document(
                document=pdf_file,
                caption="Благодарим! Делимся с вами доходностью локаций.\n"
                        "Данные аналитики относятся только к объектам под нашим управлением"
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
                    caption="Благодарим! Ваш персональный менеджер скоро свяжется с вами. А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки PDF портфеля инвестора: {e}")
                await message.answer(
                    "Благодарим! Ваш персональный менеджер скоро свяжется с вами. А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>",
                    parse_mode="HTML"
                )
            await send_subscribe_message(message)
            
    elif segment in ["investment", "living"]:
        try:
            investor_portfolio_file = FSInputFile(config.investor_portfolio_path)
            await message.answer_document(
                document=investor_portfolio_file,
                caption="Благодарим! Ваш персональный менеджер скоро свяжется с вами. А пока предлагаем изучить <b>Стратегию доходности: как получить от 40% прибыли за 1,5 года</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки PDF портфеля инвестора: {e}")
            await message.answer(
                "Благодарим! Ваш персональный менеджер скоро свяжется с вами.",
                parse_mode="HTML"
            )
        await send_subscribe_message(message)
        
    else:
        await message.answer("Благодарим! Ваш персональный менеджер скоро свяжется с вами.")
        await send_subscribe_message(message)

async def send_subscribe_message(message: Message):
    """Отправляет сообщение с картинкой подписки"""
    try:
        subscribe_img = FSInputFile(config.subscribe_image_path)
        await message.answer_photo(
            photo=subscribe_img,
            caption="",
            reply_markup=get_subscribe_keyboard()
        )
    except Exception as e:
        logger.error(f"❌ Ошибка отправки картинки подписки: {e}")
        await message.answer(
            "Узнавайте первыми о новых объектах недвижимости!",
            reply_markup=get_subscribe_keyboard()
        )