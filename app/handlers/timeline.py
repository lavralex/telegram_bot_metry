from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.keyboards.timeline import get_timeline_keyboard
from app.keyboards.management import get_management_keyboard
from app.keyboards.contact import get_policy_keyboard
from app.handlers.contact import share_contact
import logging

logger = logging.getLogger(__name__)

timeline_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@timeline_router.callback_query(F.data.startswith("timeline_"))
async def universal_timeline_handler(callback: CallbackQuery, state: FSMContext):
    # Получаем сегмент из состояния
    data = await state.get_data()
    segment = data.get('segment', 'unknown')
    
    # Обрабатываем timeline
    timeline = callback.data.replace("timeline_", "")
    timeline_text = {
        "3months": "В течение 3-х месяцев",
        "1year": "В течение года",
        "no_plan": "Не планирую в этом году"
    }.get(timeline, timeline)
    
    await state.update_data(timeline=timeline_text)
    await add_step_to_path(state, f"Срок: {timeline_text}")
    
    # В зависимости от сегмента переходим к следующему шагу
    if segment == "investment":
        # === СООБЩЕНИЕ С КАРТИНКОЙ: answer (новое сообщение) ===
        try:
            management_img = FSInputFile(config.management_image_path)
            await callback.message.answer_photo(
                photo=management_img,
                caption="Вы планируете сдавать сами или через нашу УК?",
                reply_markup=get_management_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки картинки управления: {e}")
            await callback.message.answer(
                "Вы планируете сдавать сами или через нашу УК?",
                reply_markup=get_management_keyboard()
            )
        await state.set_state("investment:waiting_for_management")
        
    elif segment == "living":
        # Переход к сбору контактов
        # === СООБЩЕНИЕ С ПОЛИТИКОЙ: answer (новое сообщение) ===
        await callback.message.answer(
            "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
            reply_markup=get_policy_keyboard()
        )
        
        # Сразу переходим к запросу контакта с Reply-клавиатурой
        await share_contact(callback, state)
    
    else:
        # fallback
        await callback.message.edit_text(
            "Ошибка: неизвестный сегмент",
            reply_markup=None
        )
    
    await callback.answer()