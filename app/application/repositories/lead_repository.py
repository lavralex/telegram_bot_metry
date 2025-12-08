from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from app.infrastructure.database.models import Lead, LinkClick, LeadStatus  # LeadStatus теперь доступен
from datetime import datetime, timedelta

class LeadRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_lead(self, lead_data: dict) -> Lead:
        lead = Lead(**lead_data)
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def get_lead_by_id(self, lead_id: int) -> Optional[Lead]:
        return self.db.query(Lead).filter(Lead.id == lead_id).first()

    def get_leads_by_segment(self, segment: str, limit: int = 100) -> List[Lead]:
        return self.db.query(Lead).filter(Lead.segment == segment).order_by(desc(Lead.created_at)).limit(limit).all()

    def update_lead_status(self, lead_id: int, status: LeadStatus) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if lead:
            lead.status = status.value  # Используем значение enum
            lead.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead

    def get_today_leads(self) -> List[Lead]:
        today = datetime.utcnow().date()
        return self.db.query(Lead).filter(Lead.created_at >= today).all()

    def get_leads_count_by_segment(self) -> dict:
        results = self.db.query(Lead.segment, func.count(Lead.id)).group_by(Lead.segment).all()
        return {segment: count for segment, count in results}

class LinkClickRepository:
    def __init__(self, db: Session):
        self.db = db

    def record_click(self, utm_source: str, user_id: Optional[int] = None, user_data: Optional[dict] = None):
        click = LinkClick(
            utm_source=utm_source,
            user_id=user_id,
            user_data=user_data or {}
        )
        self.db.add(click)
        self.db.commit()

    def get_clicks_count(self, utm_source: str = None) -> int:
        query = self.db.query(LinkClick)
        if utm_source:
            query = query.filter(LinkClick.utm_source == utm_source)
        return query.count()

    def get_popular_utm_sources(self, limit: int = 10) -> List[dict]:
        results = self.db.query(
            LinkClick.utm_source,
            func.count(LinkClick.id).label('clicks')
        ).group_by(LinkClick.utm_source).order_by(desc('clicks')).limit(limit).all()
        
        return [{"utm_source": utm, "clicks": clicks} for utm, clicks in results]