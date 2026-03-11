from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.infrastructure.database.models import Lead, LinkClick, LeadStatus


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

    def get_latest_lead_by_user_id(self, user_id: int) -> Optional[Lead]:
        return (
            self.db.query(Lead)
            .filter(Lead.user_id == user_id)
            .order_by(desc(Lead.created_at))
            .first()
        )

    def get_leads_by_segment(self, segment: str, limit: int = 100) -> List[Lead]:
        return (
            self.db.query(Lead)
            .filter(Lead.segment == segment)
            .order_by(desc(Lead.created_at))
            .limit(limit)
            .all()
        )

    def update_lead_status(self, lead_id: int, status: LeadStatus) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if lead:
            lead.status = status.value
            lead.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead

    def set_bitrix_lead_id(self, lead_id: int, bitrix_lead_id: int) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if not lead:
            return None
        lead.bitrix_lead_id = int(bitrix_lead_id)
        lead.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def set_openlines_chat_id(self, lead_id: int, openlines_chat_id: int | str) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if not lead:
            return None
        try:
            lead.openlines_chat_id = int(openlines_chat_id)
        except Exception:
            lead.openlines_chat_id = None
        lead.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def update_lead_from_state(self, lead_id: int, state_data: Dict[str, Any]) -> Optional[Lead]:
        lead = self.get_lead_by_id(lead_id)
        if not lead:
            return None

        def _non_empty(v: Any) -> bool:
            if v is None:
                return False
            if isinstance(v, str) and not v.strip():
                return False
            return True

        def _set_if_present(attr: str, value: Any) -> None:
            """Обновлять поле, если в state пришло непустое значение."""
            if not _non_empty(value):
                return
            setattr(lead, attr, value)

        def _fill_if_empty(attr: str, value: Any) -> None:
            """Заполнить поле только если оно ещё пустое (не перетирать существующее)."""
            if not _non_empty(value):
                return
            current = getattr(lead, attr, None)
            if current is None or (isinstance(current, str) and not current.strip()):
                setattr(lead, attr, value)

        _set_if_present("utm_source", state_data.get("utm_source"))
        _set_if_present("segment", state_data.get("segment"))

        _fill_if_empty("budget", state_data.get("budget"))
        _fill_if_empty("timeline", state_data.get("timeline"))
        _fill_if_empty("management", state_data.get("management"))
        _fill_if_empty("experience", state_data.get("experience"))
        _fill_if_empty("phone", state_data.get("phone"))

        incoming_path = state_data.get("user_path") or []
        if incoming_path:
            existing = lead.user_path or []
            merged = list(existing)
            for step in incoming_path:
                if step not in merged:
                    merged.append(step)
            lead.user_path = merged

        lead.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def get_today_leads(self) -> List[Lead]:
        now = datetime.utcnow()
        start = datetime(year=now.year, month=now.month, day=now.day)
        return self.db.query(Lead).filter(Lead.created_at >= start).all()

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
            user_data=user_data or {},
        )
        self.db.add(click)
        self.db.commit()

    def get_clicks_count(self, utm_source: str = None) -> int:
        query = self.db.query(LinkClick)
        if utm_source:
            query = query.filter(LinkClick.utm_source == utm_source)
        return query.count()

    def get_popular_utm_sources(self, limit: int = 10) -> List[dict]:
        results = (
            self.db.query(
                LinkClick.utm_source,
                func.count(LinkClick.id).label("clicks"),
            )
            .group_by(LinkClick.utm_source)
            .order_by(desc("clicks"))
            .limit(limit)
            .all()
        )

        return [{"utm_source": utm, "clicks": clicks} for utm, clicks in results]
