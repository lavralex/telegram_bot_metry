from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from app.keyboards.contact import get_policy_keyboard
from app.keyboards.experience import get_experience_keyboard
from app.handlers.contact import share_contact

manager_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@manager_router.callback_query(F.data == "manager")
async def manager_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(segment="manager")
    await add_step_to_path(state, "Связаться с менеджером")
    await callback.message.edit_text(
        "Ранее уже работали с нами?",
        reply_markup=get_experience_keyboard()
    )
    await state.set_state("manager:waiting_for_experience")
    await callback.answer()

@manager_router.callback_query(F.data.startswith("experience_"))
async def experience_selected(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "manager:waiting_for_experience":
        await callback.answer()
        return
        
    experience = callback.data.replace("experience_", "")
    experience_text = "уже инвестировал(а)" if experience == "invested" else "новый клиент"
    await state.update_data(experience=experience_text)
    await add_step_to_path(state, f"Опыт: {experience_text}")
    await callback.message.edit_text(
        "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
        reply_markup=get_policy_keyboard()
    )
    await share_contact(callback, state)
    await callback.answer()