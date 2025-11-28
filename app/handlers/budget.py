from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from app.keyboards.budget import get_budget_keyboard
from app.keyboards.timeline import get_timeline_keyboard

budget_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@budget_router.callback_query(F.data.startswith("budget_"))
async def universal_budget_handler(callback: CallbackQuery, state: FSMContext):
    # Получаем сегмент из состояния
    data = await state.get_data()
    segment = data.get('segment', 'unknown')
    
    # Обрабатываем бюджет
    budget = callback.data.replace("budget_", "")
    budget_text = {
        "6-10": "6-10 млн",
        "10-20": "10-20 млн", 
        "20-30": "20-30 млн",
        "30plus": "30+ млн"
    }.get(budget, budget)
    
    await state.update_data(budget=budget_text)
    await add_step_to_path(state, f"Бюджет: {budget_text}")
    
    # В зависимости от сегмента переходим к следующему шагу
    if segment == "investment":
        await callback.message.edit_text(
            "Когда планируете инвестировать?",
            reply_markup=get_timeline_keyboard("investment")
        )
        await state.set_state("investment:waiting_for_timeline")
        
    elif segment == "living":
        await callback.message.edit_text(
            "Когда планируете приобретать?",
            reply_markup=get_timeline_keyboard("living")
        )
        await state.set_state("living:waiting_for_timeline")
    
    else:
        # fallback
        await callback.message.edit_text(
            "Когда планируете?",
            reply_markup=get_timeline_keyboard()
        )
        await state.set_state("common:waiting_for_timeline")
    
    await callback.answer()