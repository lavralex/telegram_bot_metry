from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.core.dependencies import get_link_click_repository
from app.keyboards.main_menu import get_main_menu
import logging

logger = logging.getLogger(__name__)

start_router = Router()

@start_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    # Очищаем предыдущее состояние
    await state.clear()
    
    # Получаем аргументы команды /start (UTM параметры)
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    utm_source = args[0] if args else "organic"
    
    # Записываем переход в статистику
    click_repo = get_link_click_repository()
    user_data = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }
    click_repo.record_click(utm_source, message.from_user.id, user_data)
    
    # Определяем сегмент по английским UTM ключам
    segment = "unknown"
    utm_name = "organic"
    
    # Если UTM есть в наших сегментах, берем русское название
    if utm_source in config.UTM_SEGMENTS:
        utm_name = config.UTM_SEGMENTS[utm_source]
        segment = utm_name
    
    # Сохраняем в состоянии
    await state.update_data(
        utm_source=utm_source,
        segment=segment,
        user_path=[]
    )
    
    # Безопасное логирование - только ID и UTM
    logger.info(f"🚀 Новый пользователь: ID={message.from_user.id}, UTM={utm_source}")
    
    # === СТАРТОВОЕ СООБЩЕНИЕ БЕЗ КАРТИНКИ ===
    await message.answer(
        "Выберите Ваш запрос:",
        reply_markup=get_main_menu()
    )