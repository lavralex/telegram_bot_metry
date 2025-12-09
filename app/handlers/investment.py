from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.keyboards.budget import get_budget_keyboard
from app.keyboards.timeline import get_timeline_keyboard
from app.keyboards.management import get_management_keyboard
from app.keyboards.contact import get_policy_keyboard
from app.handlers.contact import share_contact
import logging

logger = logging.getLogger(__name__)

investment_router = Router()

async def add_step_to_path(state: FSMContext, step: str):
    """Добавляет шаг в путь пользователя"""
    data = await state.get_data()
    user_path = data.get('user_path', [])
    user_path.append(step)
    await state.update_data(user_path=user_path)

@investment_router.callback_query(F.data == "invest")
async def investment_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(segment="investment")
    await add_step_to_path(state, "Недвижимость для инвестиций")
    await callback.message.edit_text(
        "Ваш бюджет",
        reply_markup=get_budget_keyboard("investment")
    )
    await state.set_state("investment:waiting_for_budget")
    await callback.answer()

@investment_router.callback_query(F.data.startswith("timeline_"))
async def timeline_selected(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state != "investment:waiting_for_timeline":
        await callback.answer()
        return

    timeline = callback.data.replace("timeline_", "")
    timeline_text = {
        "3months": "В течение 3-х месяцев",
        "1year": "В течение года",
        "no_plan": "Не планирую в этом году"
    }.get(timeline, timeline)
    
    await state.update_data(timeline=timeline_text)
    await add_step_to_path(state, f"Срок: {timeline_text}")

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
    await callback.answer()

@investment_router.callback_query(F.data.startswith("management_"))
async def management_selected(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state != "investment:waiting_for_management":
        await callback.answer()
        return
        
    management_text = "самостоятельно" if callback.data == "management_self" else "через УК"
    await state.update_data(management=management_text)
    await add_step_to_path(state, f"Управление: {management_text}")

    if callback.message.photo:
        await callback.message.answer(
            "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
            reply_markup=get_policy_keyboard()
        )
    else:
        await callback.message.edit_text(
            "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
            reply_markup=get_policy_keyboard()
        )

    await share_contact(callback, state)
    await callback.answer()