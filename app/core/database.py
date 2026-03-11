from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import config

logger = logging.getLogger("bot.database")

engine = create_engine(
    config.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=True if config.ENV == "development" else False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_and_create_tables() -> None:
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        required_tables = {
            "leads",
            "link_clicks",
            "broadcasts",
            "subscribers",
            "user_messages",
            "bitrix_oauth_tokens",
        }

        missing_tables = sorted(list(required_tables - existing_tables))

        if missing_tables:
            logger.warning("⚠️ Отсутствуют таблицы: %s", missing_tables)
            logger.info("🔄 Создаем недостающие таблицы через SQLAlchemy metadata...")
            from app.infrastructure.database import models as _models  # noqa: F401

            Base.metadata.create_all(bind=engine)
            logger.info("✅ Таблицы успешно созданы")
        else:
            logger.info("✅ Все таблицы существуют")

    except Exception as e:
        logger.exception("❌ Ошибка при проверке/создании таблиц: %s", e)
        try:
            from app.infrastructure.database import models as _models  # noqa: F401

            Base.metadata.create_all(bind=engine)
            logger.info("✅ Таблицы созданы через fallback")
        except Exception as e2:
            logger.exception("❌ Критическая ошибка создания таблиц: %s", e2)


def apply_alembic_migrations() -> None:
    try:
        import alembic.config
        import alembic.command

        alembic_cfg = alembic.config.Config("alembic.ini")
        alembic.command.upgrade(alembic_cfg, "head")
        logger.info("✅ Alembic миграции применены (upgrade head)")
    except Exception as e:
        logger.exception("⚠️ Не удалось применить Alembic миграции: %s", e)
