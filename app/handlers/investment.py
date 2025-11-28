from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from app.core.config import config
from app.keyboards.budget import get_budget_keyboard
from app.keyboards.timeline import get_timeline_keyboard
from app.keyboards.management import get_management_keyboard
from app.keyboards.contact import get_contact_keyboard, get_policy_keyboard
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
    # Обновляем сегмент в состоянии
    await state.update_data(segment="investment")
    await add_step_to_path(state, "Недвижимость для инвестиций")
    
    await callback.message.answer(
        "Бюджет",
        reply_markup=get_budget_keyboard("investment")
    )
    await state.set_state("investment:waiting_for_budget")
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
    
    await callback.message.answer(
        "Продолжая диалог, Вы соглашаетесь с Политикой по обработке персональных данных",
        reply_markup=get_policy_keyboard()
    )
    
    # Второе сообщение - запрос контакта с картинкой
    try:
        management_img = FSInputFile(config.management_image_path)
        await callback.message.answer_photo(
            photo=management_img,
            caption="Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\n"
                    "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков",
            reply_markup=get_contact_keyboard("investment")
        )
    except Exception as e:
        logger.error(f"❌ Ошибка отправки картинки управления: {e}")
        await callback.message.answer(
            "Пожалуйста, авторизуйтесь, нажав кнопку внизу экрана.\n"
            "Ваши данные полностью защищены — обещаем, никаких навязчивых звонков",
            reply_markup=get_contact_keyboard("investment")
        )
    
    await state.set_state("investment:waiting_for_contact")
    await callback.answer()