from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
import logging

from app.core.config import config
from app.core.dependencies import get_link_click_repository
from app.keyboards.main_menu import get_main_menu

logger = logging.getLogger(__name__)

utm_router = Router()

@utm_router.message(CommandStart())
async def handle_start_with_utm(message: Message, state: FSMContext):
    """Обрабатывает /start с UTM параметрами"""
    await state.clear()

    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    utm_source = args[0] if args else "organic"

    click_repo = get_link_click_repository()
    user_data = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }
    click_repo.record_click(utm_source, message.from_user.id, user_data)

    segment = "unknown"
    utm_name = "organic"

    if utm_source in config.UTM_SEGMENTS:
        utm_name = config.UTM_SEGMENTS[utm_source]
        segment = utm_name

    await state.update_data(
        utm_source=utm_source,
        current_utm=utm_source,
        segment=segment,
        user_path=[]
    )

    logger.info(f"🎯 Пользователь {message.from_user.id} пришел с UTM: {utm_source} -> {utm_name}")

    await message.answer(
        "Выберите Ваш запрос:",
        reply_markup=get_main_menu()
    )

@utm_router.callback_query(F.data.startswith("utm_"))
async def handle_utm_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает UTM из callback кнопок (если будут в будущем)"""
    utm_source = callback.data
    
    if utm_source in config.UTM_SEGMENTS:
        await state.update_data(current_utm=utm_source)
        
        utm_name = config.UTM_SEGMENTS[utm_source]
        logger.info(f"🔄 Пользователь {callback.from_user.id} сменил UTM на: {utm_source} ({utm_name})")
        
        await callback.answer(f"UTM установлен: {utm_name}")
    else:
        await callback.answer("❌ Неизвестный UTM")