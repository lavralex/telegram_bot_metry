import asyncio
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Update
import logging

from app.core.config import config
from app.core.logging_config import setup_logging
from app.handlers.start import start_router
from app.handlers.investment import investment_router
from app.handlers.living import living_router
from app.handlers.manager import manager_router
from app.handlers.analytics import analytics_router
from app.handlers.back import back_router
from app.handlers.contact import contact_router
from app.handlers.budget import budget_router
from app.handlers.timeline import timeline_router
from app.handlers.admin import admin_router
from app.application.services.broadcast_service import start_broadcast_scheduler, stop_broadcast_scheduler
from app.infrastructure.external.bitrix24 import init_bitrix_client

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        logger = logging.getLogger('bot.updates')
        
        if event.callback_query:
            logger.debug(
                f"CALLBACK: {event.callback_query.data} | "
                f"User: {event.callback_query.from_user.id}"
            )
        elif event.message:
            if event.message.contact:
                # Безопасное логирование контакта - только факт получения
                logger.info(
                    f"CONTACT: User {event.message.from_user.id} shared contact"
                )
            elif event.message.text:
                # Логируем только короткий префикс текста
                text_preview = event.message.text[:30] + "..." if len(event.message.text) > 30 else event.message.text
                logger.debug(f"MESSAGE: {text_preview} | User: {event.message.from_user.id}")
        
        result = await handler(event, data)
        return result

async def shutdown():
    """Корректное завершение работы"""
    logger = logging.getLogger('bot.shutdown')
    logger.info("🛑 Завершение работы бота...")
    await stop_broadcast_scheduler()
    logger.info("✅ Все задачи завершены")

async def main():
    logger = setup_logging()
    logger.info("🚀 Запуск бота...")
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    # Добавляем middleware для логирования
    dp.update.middleware(LoggingMiddleware())
    
    routers = [
        start_router,
        back_router,
        budget_router,
        timeline_router,
        investment_router, 
        living_router,
        manager_router,
        analytics_router,
        contact_router,
        admin_router
    ]
    
    for router in routers:
        dp.include_router(router)
    
    # Инициализация Bitrix24 клиента
    if config.BITRIX24_ENABLED and config.BITRIX24_WEBHOOK_URL:
        await init_bitrix_client(config.BITRIX24_WEBHOOK_URL)
        logger.info(f"✅ Bitrix24 интеграция включена")
    else:
        logger.info("ℹ️ Bitrix24 интеграция отключена")
    
    logger.info("✅ Бот запущен с английскими UTM параметрами!")
    logger.info("📊 Доступные UTM сегменты: %s", list(config.UTM_SEGMENTS.values()))
    
    bot_username = (await bot.get_me()).username
    logger.info("🔗 Пример UTM ссылки: https://t.me/%s?start=utm_invest", bot_username)
    
    # Запускаем планировщик рассылок
    await start_broadcast_scheduler(bot)
    logger.info("📢 Планировщик рассылок запущен")
    
    try:
        logger.info("🔄 Бот начал polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал KeyboardInterrupt")
    finally:
        # Останавливаем планировщик при завершении
        await shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")
    except Exception as e:
        logging.getLogger('bot.main').error(f"❌ Критическая ошибка: {e}", exc_info=True)