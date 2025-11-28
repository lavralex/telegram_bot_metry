from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, BigInteger
from app.core.database import Base
from datetime import datetime
import enum

class LeadStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    CONVERTED = "converted"
    REJECTED = "rejected"

class BroadcastStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    segment = Column(String(50), nullable=False)
    utm_source = Column(String(100), default="organic")
    budget = Column(String(50))
    timeline = Column(String(50))
    management = Column(String(50))
    experience = Column(String(50))
    user_path = Column(JSON)
    status = Column(String(20), default=LeadStatus.NEW)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LinkClick(Base):
    __tablename__ = "link_clicks"
    
    id = Column(Integer, primary_key=True, index=True)
    utm_source = Column(String(100), nullable=False)
    user_id = Column(BigInteger)
    user_data = Column(JSON)
    clicked_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(45))

class Broadcast(Base):
    __tablename__ = "broadcasts"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    message_text = Column(Text)
    photo_url = Column(String(500))
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(String(20), default=BroadcastStatus.DRAFT)
    sent_at = Column(DateTime)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Subscriber(Base):
    __tablename__ = "subscribers"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    unsubscribed_at = Column(DateTime)