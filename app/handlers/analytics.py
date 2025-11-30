from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.keyboards.contact import get_policy_keyboard
from app.handlers.contact import share_contact

analytics_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@analytics_router.callback_query(F.data == "analytics")
async def analytics_start(callback: CallbackQuery, state: FSMContext):
    # Обновляем сегмент в состоянии
    await state.update_data(segment="analytics")
    await add_step_to_path(state, "Аналитика доходности локаций")
    
    # === СООБЩЕНИЕ С ПОЛИТИКОЙ: edit_text (заменяем предыдущее сообщение) ===
    await callback.message.edit_text(
        "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
        reply_markup=get_policy_keyboard()
    )
    
    # Сразу переходим к запросу контакта с Reply-клавиатурой
    await share_contact(callback, state)
    await callback.answer()