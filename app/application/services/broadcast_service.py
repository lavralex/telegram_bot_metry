import asyncio
from datetime import datetime
from sqlalchemy import and_
import logging

from app.core.database import SessionLocal
from app.infrastructure.database.models import Broadcast
from app.core.dependencies import get_user_repository
from aiogram.types import InputMediaPhoto

logger = logging.getLogger('bot.broadcast')

class BroadcastService:
    def __init__(self, bot):
        self.bot = bot
        self.is_running = False
        self.scheduler_task = None
        self.logger = logger

    async def start_scheduler(self):
        """Запускает планировщик рассылок"""
        self.is_running = True
        self.logger.info("🔄 Планировщик рассылок запущен")
        
        while self.is_running:
            try:
                await self.check_scheduled_broadcasts()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.logger.info("🔄 Планировщик рассылок получил сигнал отмены...")
                break
            except Exception as e:
                self.logger.error("❌ Ошибка в планировщике рассылок: %s", e)
                await asyncio.sleep(60)

    async def stop_scheduler(self):
        """Останавливает планировщик рассылок"""
        self.is_running = False
        self.logger.info("🛑 Останавливаем планировщик рассылок...")
        
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                self.logger.info("✅ Задача планировщика отменена")
        
        self.logger.info("🛑 Планировщик рассылок остановлен")

    async def check_scheduled_broadcasts(self):
        """Проверяет и отправляет запланированные рассылки"""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            broadcasts = db.query(Broadcast).filter(
                and_(
                    Broadcast.status == "scheduled",
                    Broadcast.scheduled_time <= now
                )
            ).all()
            
            for broadcast in broadcasts:
                self.logger.info("📢 Отправка запланированной рассылки: %s", broadcast.title)
                
                try:
                    user_repo = get_user_repository()
                    users = user_repo.get_all_users()
                    user_ids = [user.user_id for user in users if user.user_id]
                    photos = []
                    file_url = None
                    
                    if broadcast.photos_json:
                        photos = broadcast.photos_json
                    elif broadcast.photo_url:
                        photos = [broadcast.photo_url]
                    
                    if broadcast.file_url:
                        file_url = broadcast.file_url
                    
                    self.logger.info(f"📊 Данные рассылки: текст='{broadcast.message_text[:50]}...', фото={len(photos)} шт., файл={file_url is not None}")
                    
                    success, failed = await self.send_broadcast_to_users(
                        user_ids, 
                        broadcast.message_text, 
                        photos,
                        file_url
                    )
                    
                    broadcast.status = "sent"
                    broadcast.sent_at = datetime.utcnow()
                    db.commit()
                    
                    self.logger.info("✅ Рассылка отправлена: %d успешно, %d неудачно", success, failed)
                except Exception as e:
                    self.logger.error(f"❌ Ошибка при отправке рассылки {broadcast.id}: {e}", exc_info=True)
                    db.rollback()
                finally:
                    if 'user_repo' in locals():
                        user_repo.db.close()
                
        except Exception as e:
            self.logger.error("❌ Ошибка при проверке рассылок: %s", e, exc_info=True)
            db.rollback()
        finally:
            db.close()

    async def send_broadcast_to_users(self, users: list, text: str, photos: list = None, file: str = None) -> tuple[int, int]:
        """Отправка рассылки конкретным пользователям"""
        success = 0
        failed = 0
        
        self.logger.info("📤 Начало рассылки для %d пользователей", len(users))
        self.logger.info(f"📊 Параметры: фото={len(photos) if photos else 0} шт., файл={'есть' if file else 'нет'}")
        
        for user_id in users:
            try:
                self.logger.debug(f"📤 Отправка пользователю {user_id}")
                if photos:
                    self.logger.debug(f"  📷 Отправка {len(photos)} фото")
                    try:
                        if len(photos) == 1:
                            await self.bot.send_photo(
                                user_id,
                                photo=photos[0],
                                caption=text if text else None,
                                parse_mode='HTML'
                            )
                        else:
                            media = []
                            for i, photo_id in enumerate(photos):
                                if i == 0:
                                    media.append(InputMediaPhoto(
                                        media=photo_id, 
                                        caption=text if text else None,
                                        parse_mode='HTML'
                                    ))
                                else:
                                    media.append(InputMediaPhoto(media=photo_id))
                            
                            await self.bot.send_media_group(user_id, media)
                        self.logger.debug(f"  ✅ Фото отправлены пользователю {user_id}")
                    except Exception as e:
                        self.logger.error(f"  ❌ Ошибка отправки фото пользователю {user_id}: {e}")
                        failed += 1
                        continue
                    if file:
                        self.logger.debug(f"  📎 Отправка файла отдельным сообщением (без текста): {file}")
                        try:
                            await self.bot.send_document(
                                user_id, 
                                document=file,
                                caption=None,
                                parse_mode='HTML'
                            )
                            self.logger.debug(f"  ✅ Файл отправлен пользователю {user_id} (без текста)")
                        except Exception as e:
                            self.logger.error(f"  ❌ Ошибка отправки файла пользователю {user_id}: {e}")
                            pass
                        
                elif file:
                    self.logger.debug(f"  📎 Отправка файла с текстом: {file}")
                    try:
                        await self.bot.send_document(
                            user_id, 
                            document=file,
                            caption=text if text else None,
                            parse_mode='HTML'
                        )
                        self.logger.debug(f"  ✅ Файл отправлен пользователю {user_id}")
                    except Exception as e:
                        self.logger.error(f"  ❌ Ошибка отправки файла пользователю {user_id}: {e}")
                        failed += 1
                        continue
                        
                else:
                    self.logger.debug(f"  📝 Отправка текста")
                    try:
                        await self.bot.send_message(
                            user_id, 
                            text, 
                            parse_mode='HTML'
                        )
                        self.logger.debug(f"  ✅ Текст отправлен пользователю {user_id}")
                    except Exception as e:
                        self.logger.error(f"  ❌ Ошибка отправки текста пользователю {user_id}: {e}")
                        failed += 1
                        continue
                
                success += 1
                await asyncio.sleep(0.05)
                
            except Exception as e:
                self.logger.error(f"❌ Общая ошибка отправки пользователю {user_id}: {e}")
                failed += 1
        
        self.logger.info("📫 Рассылка завершена: %d успешно, %d неудачно", success, failed)
        return success, failed


broadcast_service = None

async def start_broadcast_scheduler(bot):
    """Запускает сервис рассылок"""
    global broadcast_service
    broadcast_service = BroadcastService(bot)
    broadcast_service.scheduler_task = asyncio.create_task(broadcast_service.start_scheduler())

async def stop_broadcast_scheduler():
    """Останавливает сервис рассылок"""
    global broadcast_service
    if broadcast_service:
        await broadcast_service.stop_scheduler()