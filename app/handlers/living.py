from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from app.keyboards.budget import get_budget_keyboard
from app.keyboards.timeline import get_timeline_keyboard

living_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@living_router.callback_query(F.data == "living")
async def living_start(callback: CallbackQuery, state: FSMContext):
    # Обновляем сегмент в состоянии
    await state.update_data(segment="living")
    await add_step_to_path(state, "Недвижимость для жизни")
    
    # === edit_text (заменяем предыдущее сообщение) ===
    await callback.message.edit_text(
        "Бюджет",
        reply_markup=get_budget_keyboard("living")
    )
    await state.set_state("living:waiting_for_budget")
    await callback.answer()