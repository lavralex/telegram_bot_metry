from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.application.repositories.lead_repository import LeadRepository, LinkClickRepository
from app.application.repositories.message_repository import MessageRepository
from app.application.repositories.user_repository import UserRepository

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

def get_user_repository():
    """Получить репозиторий пользователей"""
    db = SessionLocal()
    try:
        return UserRepository(db)
    finally:
        db.close()