from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import config
import logging

logger = logging.getLogger('bot.database')

# 👇 PostgreSQL использует пул соединений по умолчанию
engine = create_engine(
    config.DATABASE_URL,
    pool_size=10,           # Размер пула соединений
    max_overflow=20,        # Дополнительные соединения при нагрузке
    pool_pre_ping=True,     # Проверка соединений перед использованием
    echo=True if config.ENV == 'development' else False  # Логи только в разработке
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
        # Проверяем существование таблиц
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        # Список необходимых таблиц из наших моделей
        required_tables = ['leads', 'link_clicks', 'broadcasts', 'subscribers', 'user_messages']
        
        # Проверяем какие таблицы отсутствуют
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            logger.warning(f"⚠️ Отсутствуют таблицы: {missing_tables}")
            logger.info("🔄 Создаем недостающие таблицы...")
            
            # Импортируем модели для создания таблиц
            from app.infrastructure.database.models import Lead, LinkClick, Broadcast, Subscriber, UserMessage
            
            # Создаем все таблицы
            Base.metadata.create_all(bind=engine)
            
            logger.info("✅ Таблицы успешно созданы")
            
            # Создаем автоматическую миграцию
            create_auto_migration()
        else:
            logger.info("✅ Все таблицы существуют")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке таблиц: {e}")
        # В случае ошибки все равно создаем таблицы
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
        
        # Путь к alembic.ini
        alembic_cfg = alembic.config.Config("alembic.ini")
        
        # Создаем новую миграцию
        alembic.command.revision(
            alembic_cfg, 
            autogenerate=True, 
            message="Auto-generated migration"
        )
        
        # Применяем миграцию
        alembic.command.upgrade(alembic_cfg, "head")
        
        logger.info("✅ Автоматическая миграция создана и применена")
        
    except Exception as e:
        logger.error(f"⚠️ Не удалось создать автоматическую миграцию: {e}")
        logger.info("ℹ️ Таблицы созданы, но миграция не записана")