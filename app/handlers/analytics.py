from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.keyboards.contact import get_contact_keyboard, get_policy_keyboard, get_subscribe_keyboard

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
    
    # Поток как в ТЗ - отправляем новые сообщения вместо редактирования
    # === ИЗМЕНЕНИЕ: Убрали edit_text, оставили только answer ===
    await callback.message.answer(
        "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
        reply_markup=get_policy_keyboard()
    )
    await callback.message.answer(
        "Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\n"
        "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков",
        reply_markup=get_contact_keyboard("analytics")
    )
    await state.set_state("analytics:waiting_for_contact")
    await callback.answer()