from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import config
import logging

logger = logging.getLogger('bot.database')

engine = create_engine(
    config.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=True if config.ENV == 'development' else False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_and_create_tables():
    """Проверяет и создает таблицы, если их нет"""
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        required_tables = ['leads', 'link_clicks', 'broadcasts', 'subscribers', 'user_messages']
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            logger.warning(f"⚠️ Отсутствуют таблицы: {missing_tables}")
            logger.info("🔄 Создаем недостающие таблицы...")
            
            from app.infrastructure.database.models import Lead, LinkClick, Broadcast, Subscriber, UserMessage
            
            Base.metadata.create_all(bind=engine)
            
            logger.info("✅ Таблицы успешно созданы")
            
            create_auto_migration()
        else:
            logger.info("✅ Все таблицы существуют")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке таблиц: {e}")
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Таблицы созданы через fallback")
        except Exception as e2:
            logger.error(f"❌ Критическая ошибка создания таблиц: {e2}")

def create_auto_migration():
    """Создает автоматическую миграцию"""
    try:
        import alembic.config
        import alembic.command
        import os

        alembic_cfg = alembic.config.Config("alembic.ini")
        alembic.command.revision(
            alembic_cfg, 
            autogenerate=True, 
            message="Auto-generated migration"
        )
        
        alembic.command.upgrade(alembic_cfg, "head")
        
        logger.info("✅ Автоматическая миграция создана и применена")
        
    except Exception as e:
        logger.error(f"⚠️ Не удалось создать автоматическую миграцию: {e}")
        logger.info("ℹ️ Таблицы созданы, но миграция не записана")