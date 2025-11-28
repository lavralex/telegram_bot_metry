from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.core.config import config
from app.keyboards.budget import get_budget_keyboard
from app.keyboards.timeline import get_timeline_keyboard
from app.keyboards.management import get_management_keyboard
from app.keyboards.main_menu import get_main_menu
from app.keyboards.experience import get_experience_keyboard

back_router = Router()

@back_router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    # При возврате в главное меню отправляем картинку подписки
    try:
        subscribe_img = FSInputFile(config.subscribe_image_path)
        await callback.message.answer_photo(
            photo=subscribe_img,
            caption="Выберите Ваш запрос:",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        print(f"❌ Ошибка отправки картинки подписки: {e}")
        await callback.message.edit_text(
            "Выберите Ваш запрос:",
            reply_markup=get_main_menu()
        )
    await callback.answer()

@back_router.callback_query(F.data == "back_to_budget_investment")
async def back_to_budget_investment(callback: CallbackQuery, state: FSMContext):
    # Удаляем последний шаг из пути (текущий этап)
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Бюджет",
        reply_markup=get_budget_keyboard("investment")
    )
    await state.set_state("investment:waiting_for_budget")
    await callback.answer()

@back_router.callback_query(F.data == "back_to_budget_living")
async def back_to_budget_living(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Бюджет",
        reply_markup=get_budget_keyboard("living")
    )
    await state.set_state("living:waiting_for_budget")
    await callback.answer()

@back_router.callback_query(F.data == "back_to_timeline_investment")
async def back_to_timeline_investment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Когда планируете инвестировать?",
        reply_markup=get_timeline_keyboard("investment")
    )
    await state.set_state("investment:waiting_for_timeline")
    await callback.answer()

@back_router.callback_query(F.data == "back_to_timeline_living")
async def back_to_timeline_living(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Когда планируете приобретать?",
        reply_markup=get_timeline_keyboard("living")
    )
    await state.set_state("living:waiting_for_timeline")
    await callback.answer()

@back_router.callback_query(F.data == "back_to_management_investment")
async def back_to_management_investment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Вы планируете сдавать сами или через нашу УК?",
        reply_markup=get_management_keyboard()
    )
    await state.set_state("investment:waiting_for_management")
    await callback.answer()

@back_router.callback_query(F.data == "back_to_experience")
async def back_to_experience(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    await callback.message.edit_text(
        "Ранее уже работали с нами?",
        reply_markup=get_experience_keyboard()
    )
    await state.set_state("manager:waiting_for_experience")
    await callback.answer()

# ДОБАВЛЯЕМ НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ "back_to_budget" из timeline.py
@back_router.callback_query(F.data == "back_to_budget")
async def back_to_budget_generic(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_path = data.get('user_path', [])
    if user_path:
        user_path.pop()
        await state.update_data(user_path=user_path)
    
    # Определяем сегмент из состояния
    current_state = await state.get_state()
    if current_state == "living:waiting_for_timeline":
        await callback.message.edit_text(
            "Бюджет",
            reply_markup=get_budget_keyboard("living")
        )
        await state.set_state("living:waiting_for_budget")
    else:
        # По умолчанию возвращаем в главное меню
        await back_to_main(callback, state)
    
    await callback.answer()