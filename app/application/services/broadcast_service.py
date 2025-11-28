import asyncio
from datetime import datetime
from sqlalchemy import and_
import logging

from app.core.database import SessionLocal
from app.infrastructure.database.models import Broadcast, BroadcastStatus
from app.core.dependencies import get_lead_repository
from app.infrastructure.database.models import Lead

class BroadcastService:
    def __init__(self, bot):
        self.bot = bot
        self.is_running = False
        self.scheduler_task = None
        self.logger = logging.getLogger('bot.broadcast')  # === ДОБАВЛЕНИЕ ===

    async def start_scheduler(self):
        """Запускает планировщик рассылок"""
        self.is_running = True
        self.logger.info("🔄 Планировщик рассылок запущен")
        
        while self.is_running:
            try:
                await self.check_scheduled_broadcasts()
                await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            except asyncio.CancelledError:
                self.logger.info("🔄 Планировщик рассылок получил сигнал отмены...")
                break
            except Exception as e:
                self.logger.error("❌ Ошибка в планировщике рассылок: %s", e)
                await asyncio.sleep(60)  # Ждем минуту при ошибке

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
                    Broadcast.status == BroadcastStatus.SCHEDULED.value,
                    Broadcast.scheduled_time <= now
                )
            ).all()
            
            for broadcast in broadcasts:
                self.logger.info("📢 Отправка запланированной рассылки: %s", broadcast.title)
                
                success, failed = await self.send_broadcast(
                    broadcast.message_text, 
                    broadcast.photo_url
                )
                
                broadcast.status = BroadcastStatus.SENT.value
                broadcast.sent_at = datetime.utcnow()
                db.commit()
                
                self.logger.info("✅ Рассылка отправлена: %d успешно, %d неудачно", success, failed)
                
        except Exception as e:
            self.logger.error("❌ Ошибка при проверке рассылок: %s", e)
            db.rollback()
        finally:
            db.close()

    async def send_broadcast(self, text: str, photo: str = None) -> tuple[int, int]:
        """Отправка рассылки всем пользователям из базы"""
        lead_repo = get_lead_repository()
        users = set(lead.user_id for lead in lead_repo.db.query(Lead).all())
        
        success = 0
        failed = 0
        
        self.logger.info("📤 Начало рассылки для %d пользователей", len(users))
        
        for user_id in users:
            try:
                if photo:
                    await self.bot.send_photo(user_id, photo, caption=text)
                else:
                    await self.bot.send_message(user_id, text)
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                self.logger.warning("❌ Ошибка отправки пользователю %d: %s", user_id, e)
                failed += 1
        
        self.logger.info("📫 Рассылка завершена: %d успешно, %d неудачно", success, failed)
        return success, failed

# Глобальный экземпляр сервиса
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