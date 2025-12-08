from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional
import logging

from app.core.config import config
from app.core.dependencies import get_message_repository, get_lead_repository
from app.infrastructure.database.models import MessageDirection

logger = logging.getLogger('bot.admin_chat')

admin_chat_router = Router()

# Состояния для ответа пользователю
class ReplyStates(StatesGroup):
    waiting_for_reply_text = State()
    waiting_for_reply_media = State()

# Словарь для отслеживания переписки: user_id -> admin_id
active_replies = {}

# Команда для включения/выключения переписки
@admin_chat_router.message(Command("toggle_chat"))
async def toggle_chat(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    config.ENABLE_ADMIN_CHAT = not config.ENABLE_ADMIN_CHAT
    status = "✅ ВКЛЮЧЕНА" if config.ENABLE_ADMIN_CHAT else "❌ ВЫКЛЮЧЕНА"
    await message.answer(f"📢 Переписка с пользователями: {status}")

# Обработчик кнопки "Ответить"
@admin_chat_router.callback_query(F.data.startswith("reply_to_"))
async def start_reply(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    user_id = int(callback.data.replace("reply_to_", ""))
    admin_id = callback.from_user.id
    
    # Сохраняем в активные ответы
    active_replies[admin_id] = user_id
    
    # Сохраняем информацию о переписке в состоянии
    await state.update_data(
        reply_user_id=user_id,
        original_callback=callback
    )
    
    await callback.message.answer(
        f"💬 Вы отвечаете пользователю ID: {user_id}\n\n"
        f"Отправьте текст ответа (можно с фото/документом):\n"
        f"Для отмены отправьте /cancel"
    )
    
    await state.set_state(ReplyStates.waiting_for_reply_text)
    await callback.answer()

# Обработчик сообщения с ответом
@admin_chat_router.message(ReplyStates.waiting_for_reply_text)
async def process_reply_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    user_id = data.get('reply_user_id')
    
    if not user_id:
        await message.answer("❌ Ошибка: пользователь не найден")
        await state.clear()
        return
    
    # Сохраняем ответ в БД
    message_repo = get_message_repository()
    
    message_data = {
        'user_id': user_id,
        'admin_id': message.from_user.id,
        'message_text': message.text or message.caption or '',
        'direction': 'admin_to_user',
        'utm_source': 'admin_reply'
    }
    
    # Сохраняем медиа если есть
    if message.photo:
        message_data['photo_url'] = message.photo[-1].file_id
    elif message.document:
        message_data['document_url'] = message.document.file_id
    
    try:
        # Сохраняем сообщение
        db_message = message_repo.create_message(message_data)
        
        # Отправляем пользователю
        success = await send_message_to_user(
            message.bot, 
            user_id, 
            message.text or message.caption,
            message.photo[-1].file_id if message.photo else None,
            message.document.file_id if message.document else None
        )
        
        if success:
            await message.answer("✅ Ответ отправлен пользователю")
            message_repo.mark_as_delivered(db_message.id)
        else:
            await message.answer("❌ Не удалось отправить ответ. Пользователь, возможно, заблокировал бота.")
            db_message.status = 'failed'
            message_repo.db.commit()
        
        # Удаляем из активных ответов
        admin_id = message.from_user.id
        if admin_id in active_replies:
            del active_replies[admin_id]
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ответа: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

# Команда отмены
@admin_chat_router.message(Command("cancel"))
async def cancel_reply(message: Message, state: FSMContext):
    if await state.get_state() == ReplyStates.waiting_for_reply_text:
        admin_id = message.from_user.id
        if admin_id in active_replies:
            del active_replies[admin_id]
        
        await message.answer("❌ Ответ отменен")
        await state.clear()

# Обработчик просмотра профиля пользователя
@admin_chat_router.callback_query(F.data.startswith("profile_"))
async def view_user_profile(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    user_id = int(callback.data.replace("profile_", ""))
    
    message_repo = get_message_repository()
    lead_repo = get_lead_repository()
    
    try:
        # Получаем информацию о пользователе
        user_info = message_repo.get_user_info_for_message(user_id)
        lead = user_info['lead']
        
        # Формируем профиль
        profile_text = "👤 ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ\n\n"
        profile_text += f"🆔 ID: {user_id}\n"
        
        if lead:
            profile_text += f"📛 Имя: {lead.first_name or ''} {lead.last_name or ''}\n"
            profile_text += f"🔗 Username: @{lead.username}\n" if lead.username else ""
            profile_text += f"📞 Телефон: {lead.phone or 'не указан'}\n"
            profile_text += f"🏷️ Сегмент: {lead.segment}\n"
            profile_text += f"🔖 UTM: {lead.utm_source or 'organic'}\n"  # Показываем UTM из лида
            profile_text += f"💰 Бюджет: {lead.budget or 'не указан'}\n"
            profile_text += f"⏰ Создан: {lead.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        else:
            profile_text += "⚠️ Пользователь не оставлял заявку\n"
        
        # Получаем последнее сообщение для определения текущего UTM
        last_message = message_repo.get_user_messages(user_id, limit=1)
        if last_message:
            profile_text += f"\n📊 Последний UTM в сообщениях: {last_message[0].utm_source or 'неизвестен'}"
        else:
            profile_text += f"\n📊 Последний UTM: {user_info['last_utm'] or 'неизвестен'}"
        
        # Получаем историю сообщений
        messages = message_repo.get_user_messages(user_id, limit=5)
        if messages:
            profile_text += "\n\n📨 Последние сообщения:"
            for msg in reversed(messages):
                direction = "👤→" if msg.direction == 'user_to_admin' else "👨‍💼→"
                preview = msg.message_text[:50] + "..." if len(msg.message_text) > 50 else msg.message_text
                utm_display = f" [{msg.utm_source}]" if msg.utm_source and msg.utm_source != 'organic' else ""
                profile_text += f"\n{direction} {preview}{utm_display}"
        
        await callback.message.answer(profile_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения профиля: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        # Закрываем соединения с БД
        message_repo.db.close()
        lead_repo.db.close()
    
    await callback.answer()

async def send_message_to_user(bot, user_id: int, text: str = None, 
                              photo: str = None, document: str = None) -> bool:
    """Отправляет сообщение пользователю"""
    try:
        if photo:
            await bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=text or "",
                parse_mode='HTML'
            )
        elif document:
            await bot.send_document(
                chat_id=user_id,
                document=document,
                caption=text or ""
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=text or "Новое сообщение от менеджера",
                parse_mode='HTML'
            )
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")
        return False

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# Команда для просмотра непрочитанных сообщений
@admin_chat_router.message(Command("unread"))
async def show_unread_messages(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    message_repo = get_message_repository()
    unread_messages = message_repo.get_unread_messages_for_admin()
    
    if not unread_messages:
        await message.answer("📭 Нет непрочитанных сообщений")
        return
    
    await message.answer(f"📨 Непрочитанных сообщений: {len(unread_messages)}")
    
    for msg in unread_messages[:10]:  # Показываем первые 10
        user_info = message_repo.get_user_info_for_message(msg.user_id)
        lead = user_info['lead']
        
        preview = f"💬 Сообщение от {msg.user_id}: "
        preview += msg.message_text[:100] + "..." if len(msg.message_text) > 100 else msg.message_text
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"reply_to_{msg.user_id}"
                )],
                [InlineKeyboardButton(
                    text="✅ Прочитано",
                    callback_data=f"read_{msg.id}"
                )]
            ]
        )
        
        await message.answer(preview, reply_markup=keyboard)

# Отметка сообщения как прочитанного
@admin_chat_router.callback_query(F.data.startswith("read_"))
async def mark_as_read(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    message_id = int(callback.data.replace("read_", ""))
    message_repo = get_message_repository()
    
    message_repo.mark_as_read(message_id)
    await callback.answer("✅ Сообщение отмечено как прочитанное")
    
    # Удаляем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)