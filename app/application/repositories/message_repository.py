from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from typing import List, Optional
from datetime import datetime
from app.infrastructure.database.models import UserMessage, MessageDirection, MessageStatus, Lead
from app.core.database import SessionLocal

class MessageRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_message(self, message_data: dict) -> UserMessage:
        message = UserMessage(**message_data)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message
    
    def get_user_messages(self, user_id: int, limit: int = 50) -> List[UserMessage]:
        return self.db.query(UserMessage).filter(
            UserMessage.user_id == user_id
        ).order_by(desc(UserMessage.created_at)).limit(limit).all()
    
    def get_unread_messages_for_admin(self) -> List[UserMessage]:
        return self.db.query(UserMessage).filter(
            and_(
                UserMessage.direction == MessageDirection.USER_TO_ADMIN,
                UserMessage.status != MessageStatus.READ
            )
        ).order_by(UserMessage.created_at).all()
    
    def mark_as_read(self, message_id: int) -> Optional[UserMessage]:
        message = self.db.query(UserMessage).filter(UserMessage.id == message_id).first()
        if message:
            message.status = MessageStatus.READ
            message.read_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(message)
        return message
    
    def mark_as_delivered(self, message_id: int) -> Optional[UserMessage]:
        message = self.db.query(UserMessage).filter(UserMessage.id == message_id).first()
        if message:
            message.status = MessageStatus.DELIVERED
            message.delivered_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(message)
        return message
    
    def get_user_info_for_message(self, user_id: int) -> dict:
        """Получает информацию о пользователе для отображения админу"""
        # Ищем лида пользователя
        lead = self.db.query(Lead).filter(Lead.user_id == user_id).order_by(desc(Lead.created_at)).first()
        
        # Ищем последние UTM метки из сообщений
        last_message = self.db.query(UserMessage).filter(
            UserMessage.user_id == user_id
        ).order_by(desc(UserMessage.created_at)).first()
        
        return {
            'lead': lead,
            'last_utm': last_message.utm_source if last_message else None,
            'user_id': user_id
        }

# Фабричная функция для зависимостей
def get_message_repository():
    db = SessionLocal()
    try:
        return MessageRepository(db)
    finally:
        db.close()