from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import config

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