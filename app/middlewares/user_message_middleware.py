from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from typing import Callable, Dict, Any, Awaitable
import logging
from app.core.config import config
from app.core.dependencies import get_message_repository, get_lead_repository
from app.infrastructure.database.models import Lead
from sqlalchemy import desc

logger = logging.getLogger('bot.messages')

class UserMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Проверяем, что это сообщение
        if not event.message:
            return await handler(event, data)
            
        message = event.message
        
        # Проверяем, что это обычное сообщение в личном чате
        if message.chat.type == "private":
            user_id = message.from_user.id
            
            # Пропускаем команды
            if message.text and message.text.startswith('/'):
                return await handler(event, data)
            
            # Пропускаем сообщения от админов
            if user_id in config.ADMIN_IDS:
                return await handler(event, data)
            
            # Проверяем, есть ли текст, фото или документ
            if not (message.text or message.photo or message.document):
                return await handler(event, data)
            
            # Получаем репозитории
            message_repo = get_message_repository()
            lead_repo = get_lead_repository()
            
            try:
                # Ищем лида пользователя
                lead = lead_repo.db.query(Lead).filter(
                    Lead.user_id == user_id
                ).order_by(desc(Lead.created_at)).first()
                
                # Определяем правильный UTM:
                # 1. Если есть лид - берем utm_source из лида (это первоначальный и правильный UTM)
                # 2. Если нет лида - пробуем получить из состояния
                # 3. Если нет ничего - используем 'organic'
                
                utm_to_use = "organic"
                
                if lead and lead.utm_source:
                    utm_to_use = lead.utm_source  # Это первоначальный и правильный UTM
                    logger.info(f"✅ Используем UTM из лида: {utm_to_use}")
                else:
                    # Пробуем получить из состояния
                    state = data.get('state')
                    if state:
                        state_data = await state.get_data()
                        utm_from_state = state_data.get('utm_source', 'organic')
                        if utm_from_state != 'organic':
                            utm_to_use = utm_from_state
                            logger.info(f"ℹ️ Используем UTM из состояния: {utm_to_use}")
                
                # Сохраняем сообщение от пользователя
                message_data = {
                    'user_id': user_id,
                    'message_text': message.text or message.caption or '',
                    'direction': 'user_to_admin',
                    'utm_source': utm_to_use,  # Используем правильный UTM!
                    'lead_id': lead.id if lead else None
                }
                
                # Сохраняем фото если есть
                if message.photo:
                    message_data['photo_url'] = message.photo[-1].file_id
                
                # Сохраняем документ если есть
                if message.document:
                    message_data['document_url'] = message.document.file_id
                
                db_message = message_repo.create_message(message_data)
                logger.info(f"💬 Сообщение от пользователя {user_id} сохранено, UTM: {utm_to_use}")
                
                # Пересылаем админам с ПРАВИЛЬНЫМ UTM
                await self.forward_to_admins(message, user_id, lead, utm_to_use)
                
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения сообщения: {e}")
            finally:
                # Закрываем сессии БД
                if 'message_repo' in locals():
                    message_repo.db.close()
                if 'lead_repo' in locals():
                    lead_repo.db.close()
        
        return await handler(event, data)
    
    async def forward_to_admins(self, message: Message, user_id: int, lead: Any = None, correct_utm: str = None):
        """Пересылает сообщение всем админам"""
        bot = message.bot
        
        # Формируем информацию о пользователе
        user_info = f"👤 {message.from_user.first_name or ''} {message.from_user.last_name or ''}"
        username = f" (@{message.from_user.username})" if message.from_user.username else ""
        user_info += username
        
        contact_info = ""
        if lead and lead.phone:
            contact_info = f"📞 {lead.phone}"
        
        # Используем ПРАВИЛЬНЫЙ UTM
        utm_info = f"🏷️ UTM: {correct_utm if correct_utm else 'organic'}"
        
        # Формируем полное сообщение для админа
        admin_message = f"💬 НОВОЕ СООБЩЕНИЕ\n\n"
        admin_message += f"{user_info}\n"
        admin_message += f"{contact_info}\n" if contact_info else ""
        admin_message += f"{utm_info}\n"
        admin_message += f"🆔 ID: {user_id}\n\n"
        
        if message.text:
            admin_message += f"📝 Текст:\n{message.text}"
        elif message.caption:
            admin_message += f"📝 Текст:\n{message.caption}"
        
        # Клавиатура с кнопкой ответа
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        reply_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"reply_to_{user_id}"
                )],
                [InlineKeyboardButton(
                    text="📊 Профиль пользователя",
                    callback_data=f"profile_{user_id}"
                )]
            ]
        )
        
        # Отправляем всем админам
        for admin_id in config.ADMIN_IDS:
            try:
                if message.photo:
                    # Отправляем фото с подписью
                    await bot.send_photo(
                        chat_id=admin_id,
                        photo=message.photo[-1].file_id,
                        caption=admin_message,
                        reply_markup=reply_keyboard
                    )
                elif message.document:
                    # Отправляем документ с подписью
                    await bot.send_document(
                        chat_id=admin_id,
                        document=message.document.file_id,
                        caption=admin_message,
                        reply_markup=reply_keyboard
                    )
                else:
                    # Отправляем текстовое сообщение
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=reply_keyboard
                    )
                logger.info(f"📤 Сообщение переслано админу {admin_id}, UTM: {correct_utm}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")