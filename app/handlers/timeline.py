from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from app.keyboards.timeline import get_timeline_keyboard
from app.keyboards.management import get_management_keyboard
from app.keyboards.contact import get_contact_keyboard, get_policy_keyboard

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
        await callback.message.edit_text(
            "Вы планируете сдавать сами или через нашу УК?",
            reply_markup=get_management_keyboard()
        )
        await state.set_state("investment:waiting_for_management")
        
    elif segment == "living":
        # Переход к сбору контактов
        await callback.message.edit_text(
            "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
            reply_markup=get_policy_keyboard()
        )
        await callback.message.answer(
            "Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\n"
            "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков",
            reply_markup=get_contact_keyboard("living")
        )
        await state.set_state("living:waiting_for_contact")
    
    else:
        # fallback
        await callback.message.edit_text(
            "Ошибка: неизвестный сегмент",
            reply_markup=None
        )
    
    await callback.answer()