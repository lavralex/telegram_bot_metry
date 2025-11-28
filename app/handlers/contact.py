from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.core.dependencies import get_lead_repository
from app.application.services.lead_service import LeadService
from app.keyboards.contact import get_subscribe_keyboard, get_contact_keyboard
from app.infrastructure.external.bitrix24 import create_bitrix_contact
import logging

logger = logging.getLogger(__name__)

contact_router = Router()

def get_contact_request_keyboard():
    """Создает клавиатуру для запроса контакта"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

@contact_router.callback_query(F.data == "share_contact")
async def share_contact(callback: CallbackQuery, state: FSMContext):
    # Проверяем, что мы в правильном состоянии для обработки контакта
    current_state = await state.get_state()
    valid_states = [
        "investment:waiting_for_contact",
        "living:waiting_for_contact", 
        "manager:waiting_for_contact",
        "analytics:waiting_for_contact"
    ]
    
    if current_state not in valid_states:
        await callback.answer("❌ Неверное состояние для отправки контакта", show_alert=True)
        return
    
    # Вместо редактирования сообщения отправляем новое сообщение
    await callback.message.answer(
        "Пожалуйста, нажмите кнопку ниже, чтобы поделиться вашим номером телефона:"
    )
    
    await callback.message.answer(
        "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков",
        reply_markup=get_contact_request_keyboard()
    )
    
    await state.set_state("waiting_for_phone_contact")
    await callback.answer()

@contact_router.message(F.contact)
async def process_contact_all(message: Message, state: FSMContext):
    if not message.contact:
        return
    
    # Сохраняем телефон в состоянии
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    
    # Получаем все данные из состояния
    user_data = await state.get_data()
    
    # Сохраняем лид в базу данных
    lead_repo = get_lead_repository()
    lead_service = LeadService(lead_repo)
    
    user_info = {
        "id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }
    
    try:
        lead = lead_service.create_lead_from_state(user_info, user_data)
        logger.info(f"✅ Лид сохранен в БД с ID: {lead.id}")
        
        # Логируем без личных данных
        await log_lead_info_safe(user_info, user_data, lead.id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения лида: {e}")
        await message.answer("Произошла ошибка при сохранении данных. Попробуйте позже.")
        return
    
    # Отправка в Bitrix24
    if config.BITRIX24_ENABLED:
        try:
            bitrix_data = {
                **user_info,
                **user_data
            }
            
            bitrix_result = await create_bitrix_contact(bitrix_data)
            if bitrix_result['success']:
                logger.info(f"✅ Лид успешно создан в Bitrix24, ID: {bitrix_result['contact_id']}")
            else:
                logger.warning(f"⚠️ Ошибка создания лида в Bitrix24: {bitrix_result['error']}")
        except Exception as e:
            logger.error(f"⚠️ Ошибка при отправке в Bitrix24: {e}")
    
    # Убираем клавиатуру
    await message.answer(
        "Спасибо! Ваш контакт получен.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Отправляем финальные сообщения в зависимости от сегмента
    segment = user_data.get('segment', 'unknown')
    await send_final_messages(message, segment, user_data)
    
    await state.clear()

@contact_router.message(F.contact, F.state == "waiting_for_phone_contact")
async def process_contact_with_state(message: Message, state: FSMContext):
    await process_contact_all(message, state)

async def log_lead_info_safe(user_info: dict, user_data: dict, lead_id: int):
    """Безопасно логирует информацию о лиде без персональных данных"""
    segment = user_data.get('segment', 'unknown')
    utm_source = user_data.get('utm_source', 'organic')
    user_path = user_data.get('user_path', [])
    
    # Определяем источник трафика
    traffic_source = "органический"
    if utm_source != "organic":
        for utm_key, utm_name in config.UTM_SEGMENTS.items():
            if utm_key == utm_source:
                traffic_source = f"UTM ({utm_name})"
                break
        else:
            traffic_source = f"UTM ({utm_source})"
    
    # Формируем путь пользователя без личных данных
    user_journey = " → ".join(user_path)
    
    # Логируем только безопасные данные
    logger.info(f"""
🎯 НОВЫЙ ЛИД СОХРАНЕН В БАЗУ!
📋 ID лида: {lead_id}
📊 Сегмент: {segment}
🔗 Источник трафика: {traffic_source}
🏷️ UTM метка: {utm_source}
🛣️ Путь пользователя: {user_journey}
👤 User ID: {user_info.get('id')}
    """)

async def send_final_messages(message: Message, segment: str, user_data: dict):
    """Отправляет финальные сообщения в зависимости от сегмента"""
    if segment == "analytics":
        # Отправляем PDF файл с аналитикой
        try:
            pdf_file = FSInputFile(config.analytics_pdf_path)
            await message.answer_document(
                document=pdf_file,
                caption="**АНАЛИТИКА ДОХОДНОСТИ ЛОКАЦИЙ**\n\n"
                        "Данные аналитики относятся только к объектам под нашим управлением"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки PDF: {e}")
            await message.answer(
                "**АНАЛИТИКА ДОХОДНОСТИ ЛОКАЦИЙ**\n\n"
                "К сожалению, файл аналитики временно недоступен.\n"
                "Наш менеджер свяжется с вами и отправит актуальные данные."
            )
        
        # Отправляем картинку подписки
        try:
            subscribe_img = FSInputFile(config.subscribe_image_path)
            await message.answer_photo(
                photo=subscribe_img,
                caption="Будьте в курсе новых инвестиционных возможностей!",
                reply_markup=get_subscribe_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка отправки картинки подписки: {e}")
            await message.answer(
                "Будьте в курсе новых инвестиционных возможностей!",
                reply_markup=get_subscribe_keyboard()
            )
        
    elif segment == "manager":
        experience = user_data.get('experience', '')
        if experience == "уже инвестировал(а)":
            await message.answer("Отлично! Персональный менеджер скоро свяжется с Вами!")
        else:
            await message.answer("Благодарим! Ваш персональный менеджер скоро свяжется с вами.")
            
            # Отправляем картинку подписки
            try:
                subscribe_img = FSInputFile(config.subscribe_image_path)
                await message.answer_photo(
                    photo=subscribe_img,
                    caption="Подпишитесь на наш канал, чтобы быть в курсе новых предложений!",
                    reply_markup=get_subscribe_keyboard()
                )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки картинки подписки: {e}")
                await message.answer(
                    "Подпишитесь на наш канал, чтобы быть в курсе новых предложений!",
                    reply_markup=get_subscribe_keyboard()
                )
            
    else:  # investment и living
        await message.answer("Благодарим! Ваш персональный менеджер скоро свяжется с вами.")
        
        # Отправляем картинку подписки
        try:
            subscribe_img = FSInputFile(config.subscribe_image_path)
            await message.answer_photo(
                photo=subscribe_img,
                caption="Узнавайте первыми о новых объектах недвижимости!",
                reply_markup=get_subscribe_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки картинки подписки: {e}")
            await message.answer(
                "Узнавайте первыми о новых объектах недвижимости!",
                reply_markup=get_subscribe_keyboard()
            )