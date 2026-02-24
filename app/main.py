from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
import uvicorn

from app.core.config import config
from app.core.logging_config import setup_logging
from app.core.database import apply_alembic_migrations, check_and_create_tables

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
from app.handlers.utm_handler import utm_router
from app.handlers.fallback import fallback_router

from app.middlewares.user_message_middleware import UserMessageMiddleware
from app.application.services.broadcast_service import (
    start_broadcast_scheduler,
    stop_broadcast_scheduler,
)

from app.infrastructure.external.bitrix_http_server import create_app
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService


async def shutdown():
    """Корректное завершение работы"""
    logger = logging.getLogger("bot.shutdown")
    logger.info("🛑 Завершение работы бота...")
    await stop_broadcast_scheduler()
    logger.info("✅ Все задачи завершены")


async def _try_bootstrap_bitrix(logger: logging.Logger) -> None:
    """
    Не блокирует старт бота.
    Если OAuth уже настроен (токены есть) — пробуем довести интеграцию до готовности.
    """
    if not config.BITRIX24_ENABLED:
        return
    if not bool(getattr(config, "BITRIX24_USE_OAUTH", False)):
        return

    await asyncio.sleep(1.0)

    try:
        oauth = BitrixOAuthService()
        if not oauth.has_valid_token():
            logger.info("ℹ️ Bitrix bootstrap skipped: OAuth tokens not found yet (install app first)")
            return

        from app.infrastructure.external.bitrix24 import ensure_bitrix_ready
        res = await ensure_bitrix_ready()
        logger.info("✅ Bitrix bootstrap on startup: %s", str(res)[:1200])
    except Exception as e:
        logger.error("Bitrix bootstrap on startup failed: %s", e, exc_info=True)


async def main():
    logger = setup_logging()
    logger.info("🚀 Запуск бота...")

    if config.AUTO_MIGRATE:
        try:
            logger.info("🔄 Применяем Alembic миграции (upgrade head)...")
            apply_alembic_migrations()
        except Exception:
            logger.warning("⚠️ Alembic не отработал, пробуем fallback create_all()")
            check_and_create_tables()
    else:
        logger.info("ℹ️ AUTO_MIGRATE выключен — пропускаем миграции")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    if config.BITRIX24_ENABLED and getattr(config, "BITRIX24_OPENLINES_ENABLED", True):
        dp.update.middleware(UserMessageMiddleware())
        logger.info("✅ Middleware для сообщений включен (OpenLines)")
    elif config.ENABLE_ADMIN_CHAT:
        dp.update.middleware(UserMessageMiddleware())
        logger.info("✅ Middleware для сообщений включен (admin-chat)")
    else:
        logger.info("ℹ️ Middleware для сообщений выключен")

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
        admin_chat_router,
        fallback_router,
    ]

    for router in routers:
        dp.include_router(router)

    http_server_task = None

    if config.BITRIX24_ENABLED:
        fastapi_app = create_app(bot)

        uv_config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=8090,
            log_level="info",
            access_log=False,
        )

        server = uvicorn.Server(uv_config)
        http_server_task = asyncio.create_task(server.serve())

        logger.info("✅ FastAPI Bitrix server запущен на http://127.0.0.1:8090")

        asyncio.create_task(_try_bootstrap_bitrix(logger))
    else:
        logger.info("ℹ️ FastAPI Bitrix server выключен")

    bot_username = (await bot.get_me()).username
    logger.info("✅ Бот запущен")
    logger.info("📊 Доступные UTM сегменты: %s", list(config.UTM_SEGMENTS.values()))
    logger.info("🔗 Пример UTM ссылки: https://t.me/%s?start=utm_invest", bot_username)

    await start_broadcast_scheduler(bot)
    logger.info("📢 Планировщик рассылок запущен")

    if config.ENABLE_ADMIN_CHAT:
        logger.info("💬 Переписка админа с пользователями ВКЛЮЧЕНА")
        logger.info("👥 Админы: %s", config.ADMIN_IDS)
    else:
        logger.info("🔇 Переписка админа с пользователями ВЫКЛЮЧЕНА")

    try:
        logger.info("🔄 Бот начал polling...")
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("🛑 Получен KeyboardInterrupt")

    except Exception as e:
        logger.error("❌ Критическая ошибка: %s", e, exc_info=True)

    finally:
        if http_server_task:
            http_server_task.cancel()

        await shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")
