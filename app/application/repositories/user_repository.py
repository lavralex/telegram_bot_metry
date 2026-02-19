from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_, case
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.infrastructure.database.models import BotUser, Lead, UserMessage
import logging

logger = logging.getLogger('bot.user_repository')

class UserRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_user(self, user_data: Dict[str, Any], utm_source: str = "organic") -> BotUser:
        user_id = user_data.get("user_id") or user_data.get("id")
        
        if not user_id:
            logger.error(f"❌ Не удалось получить user_id из данных: {user_data}")
            raise ValueError("user_id не найден в user_data")
        
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        
        if not user:
            user = BotUser(
                user_id=user_id,
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                last_name=user_data.get("last_name"),
                last_utm_source=utm_source,
                first_seen_at=datetime.utcnow(),
                last_activity_at=datetime.utcnow(),
                user_metadata={
                    "created_via": "start_command",
                    "utm_source": utm_source,
                    "full_name": f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
                }
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            logger.info(f"✅ Создан новый пользователь: {user.user_id}, UTM: {utm_source}")
        else:
            user.last_activity_at = datetime.utcnow()
            if utm_source != "organic":
                user.last_utm_source = utm_source
            self.db.commit()
            logger.info(f"🔄 Обновлена активность пользователя: {user.user_id}")
        
        return user
    
    def update_user_activity(self, user_id: int, segment: str = None, user_path: List[str] = None):
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        if user:
            user.last_activity_at = datetime.utcnow()
            if segment:
                user.last_segment = segment
            if user_path:
                user.last_user_path = user_path
            self.db.commit()
            logger.debug(f"📝 Обновлена активность для пользователя {user_id}")
    
    def mark_contact_shared(self, user_id: int, phone: str):
        """Отметить, что пользователь поделился контактом"""
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        if user:
            user.has_contact = True
            user.phone = phone
            user.contact_shared_at = datetime.utcnow()
            self.db.commit()
            logger.info(f"📞 Пользователь {user_id} поделился контактом: {phone}")
    
    def mark_lead_created(self, user_id: int):
        """Отметить, что пользователь создал лид"""
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        if user:
            user.has_lead = True
            user.lead_created_at = datetime.utcnow()

            lead = self.db.query(Lead).filter(
                Lead.user_id == user_id
            ).order_by(desc(Lead.created_at)).first()
            
            if lead:
                user.user_metadata = user.user_metadata or {}
                user.user_metadata.update({
                    "lead_id": lead.id,
                    "lead_segment": lead.segment,
                    "lead_budget": lead.budget,
                    "lead_status": lead.status,
                    "lead_created_at": lead.created_at.isoformat()
                })
            
            self.db.commit()
            logger.info(f"🎯 Пользователь {user_id} создал лид")
    
    def mark_subscribed(self, user_id: int, is_subscribed: bool = True):
        """Обновить статус подписки"""
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        if user:
            user.is_subscriber = is_subscribed
            self.db.commit()
            logger.info(f"📢 Пользователь {user_id} подписался на рассылку")
    
    def update_chat_status(self, user_id: int, has_chatted: bool = True):
        """Обновить статус чата с админом"""
        user = self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
        if user:
            user.has_chatted_with_admin = has_chatted

            unread_count = self.db.query(UserMessage).filter(
                and_(
                    UserMessage.user_id == user_id,
                    UserMessage.direction == "user_to_admin",
                    UserMessage.status != "read"
                )
            ).count()
            
            user.unread_admin_messages = unread_count
            self.db.commit()
            logger.info(f"💬 Обновлен статус чата для пользователя {user_id}: {has_chatted}")
    
    def get_user_stats(self) -> Dict[str, Any]:
        """Получить общую статистику пользователей"""
        total_users = self.db.query(BotUser).count()
        users_with_contact = self.db.query(BotUser).filter(BotUser.has_contact == True).count()
        users_with_lead = self.db.query(BotUser).filter(BotUser.has_lead == True).count()
        active_today = self.db.query(BotUser).filter(
            BotUser.last_activity_at >= datetime.utcnow() - timedelta(days=1)
        ).count()
        
        stats = {
            "total_users": total_users,
            "users_with_contact": users_with_contact,
            "users_with_lead": users_with_lead,
            "active_today": active_today,
            "conversion_to_contact": (users_with_contact / total_users * 100) if total_users > 0 else 0,
            "conversion_to_lead": (users_with_lead / total_users * 100) if total_users > 0 else 0
        }
        
        logger.debug(f"📊 Получена статистика пользователей: {stats}")
        return stats
    
    def get_users_by_utm(self, utm_source: str = None) -> List[Dict[str, Any]]:
        """Получить пользователей по UTM"""
        query = self.db.query(BotUser)
        
        if utm_source:
            query = query.filter(BotUser.last_utm_source == utm_source)
        
        users = query.order_by(desc(BotUser.last_activity_at)).all()
        
        result = []
        for user in users:
            lead = self.db.query(Lead).filter(
                Lead.user_id == user.user_id
            ).order_by(desc(Lead.created_at)).first()

            last_message = self.db.query(UserMessage).filter(
                UserMessage.user_id == user.user_id
            ).order_by(desc(UserMessage.created_at)).first()
            
            result.append({
                "user_id": user.user_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "utm_source": user.last_utm_source,
                "has_contact": user.has_contact,
                "has_lead": user.has_lead,
                "is_subscriber": user.is_subscriber,
                "last_activity": user.last_activity_at,
                "lead_info": {
                    "exists": bool(lead),
                    "segment": lead.segment if lead else None,
                    "budget": lead.budget if lead else None,
                    "status": lead.status if lead else None,
                    "created_at": lead.created_at if lead else None
                } if lead else None,
                "last_message": {
                    "text": last_message.message_text[:100] + "..." if last_message and len(last_message.message_text) > 100 else 
                           (last_message.message_text if last_message else None),
                    "time": last_message.created_at if last_message else None,
                    "direction": last_message.direction if last_message else None
                } if last_message else None,
                "user_status": self._get_user_status(user)
            })
        
        logger.debug(f"📋 Получено {len(result)} пользователей по UTM: {utm_source}")
        return result
    
    def _get_user_status(self, user: BotUser) -> str:
        """Определить статус пользователя"""
        if not user.has_contact:
            return "visitor"
        elif user.has_contact and not user.has_lead:
            return "contact_only"
        elif user.has_lead:
            lead = self.db.query(Lead).filter(Lead.user_id == user.user_id).order_by(desc(Lead.created_at)).first()
            if lead:
                return f"lead_{lead.status}"
            return "lead"
        return "unknown"
    
    def get_utm_stats_detailed(self) -> Dict[str, Any]:
        """Подробная статистика по UTM"""
        results = self.db.query(
            BotUser.last_utm_source,
            func.count(BotUser.id).label('total_users'),
            func.sum(case((BotUser.has_contact == True, 1), else_=0)).label('with_contact'),
            func.sum(case((BotUser.has_lead == True, 1), else_=0)).label('with_lead')
        ).group_by(BotUser.last_utm_source).all()
        
        stats = {}
        for utm, total, with_contact, with_lead in results:
            stats[utm] = {
                "total_users": total or 0,
                "with_contact": with_contact or 0,
                "with_lead": with_lead or 0,
                "contact_rate": (with_contact / total * 100) if total and total > 0 else 0,
                "lead_rate": (with_lead / total * 100) if total and total > 0 else 0
            }
        
        logger.debug(f"📈 Получена детальная статистика по UTM: {len(stats)} записей")
        return stats
    
    def get_all_users(self, limit: int = 100) -> List[BotUser]:
        """Получить всех пользователей"""
        return self.db.query(BotUser).order_by(desc(BotUser.last_activity_at)).limit(limit).all()
    
    def get_user_by_id(self, user_id: int) -> Optional[BotUser]:
        """Получить пользователя по ID"""
        return self.db.query(BotUser).filter(BotUser.user_id == user_id).first()
    
    def delete_user(self, user_id: int) -> bool:
        """Удалить пользователя"""
        user = self.get_user_by_id(user_id)
        if user:
            self.db.delete(user)
            self.db.commit()
            logger.info(f"🗑️ Удален пользователь: {user_id}")
            return True
        return False