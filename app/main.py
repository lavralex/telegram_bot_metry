import asyncio
from aiogram import Bot, Dispatcher
import logging

from app.core.config import config
from app.core.logging_config import setup_logging
from app.core.database import check_and_create_tables
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
from app.handlers.admin_chat import admin_chat_router
from app.middlewares.user_message_middleware import UserMessageMiddleware
from app.application.services.broadcast_service import start_broadcast_scheduler, stop_broadcast_scheduler
from app.infrastructure.external.bitrix24 import init_bitrix_client
from app.handlers.utm_handler import utm_router

async def shutdown():
    """Корректное завершение работы"""
    logger = logging.getLogger('bot.shutdown')
    logger.info("🛑 Завершение работы бота...")
    await stop_broadcast_scheduler()
    logger.info("✅ Все задачи завершены")

async def main():
    logger = setup_logging()
    logger.info("🚀 Запуск бота...")
    
    # Проверяем и создаем таблицы при запуске
    if config.AUTO_MIGRATE:
        logger.info("🔄 Проверка и создание таблиц...")
        check_and_create_tables()
    else:
        logger.info("ℹ️ Автоматическая миграция отключена")
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    # Добавляем middleware для перехвата сообщений пользователей
    if config.ENABLE_ADMIN_CHAT:
        # Правильная регистрация middleware для всех типов событий
        dp.update.middleware(UserMessageMiddleware())
        logger.info("✅ Middleware для переписки включен")
    
    routers = [
        utm_router,
        start_router,
        back_router,
        budget_router,
        timeline_router,
        investment_router, 
        living_router,
        manager_router,
        analytics_router,
        contact_router,
        admin_router,
        admin_chat_router
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
    
    # Логируем информацию о переписке
    if config.ENABLE_ADMIN_CHAT:
        logger.info("💬 Функционал переписки админа с пользователями ВКЛЮЧЕН")
        logger.info("👥 Админы: %s", config.ADMIN_IDS)
    else:
        logger.info("🔇 Функционал переписки админа с пользователями ВЫКЛЮЧЕН")
    
    try:
        logger.info("🔄 Бот начал polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал KeyboardInterrupt")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        # Останавливаем планировщик при завершении
        await shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")