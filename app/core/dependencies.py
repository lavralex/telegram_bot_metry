from app.core.database import SessionLocal
from app.application.repositories.lead_repository import LeadRepository, LinkClickRepository
from app.application.repositories.message_repository import MessageRepository, get_message_repository

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_lead_repository():
    db = SessionLocal()
    try:
        return LeadRepository(db)
    finally:
        db.close()

def get_link_click_repository():
    db = SessionLocal()
    try:
        return LinkClickRepository(db)
    finally:
        db.close()

def get_message_repository():
    """Получить репозиторий сообщений"""
    db = SessionLocal()
    try:
        return MessageRepository(db)
    finally:
        db.close()