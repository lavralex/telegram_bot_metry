from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.application.repositories.lead_repository import LeadRepository, LinkClickRepository
from app.application.repositories.message_repository import MessageRepository
from app.application.repositories.user_repository import UserRepository


def get_db() -> Session:
    return SessionLocal()


def get_lead_repository() -> LeadRepository:
    db = SessionLocal()
    return LeadRepository(db)


def get_link_click_repository() -> LinkClickRepository:
    db = SessionLocal()
    return LinkClickRepository(db)


def get_message_repository() -> MessageRepository:
    db = SessionLocal()
    return MessageRepository(db)


def get_user_repository() -> UserRepository:
    db = SessionLocal()
    return UserRepository(db)
