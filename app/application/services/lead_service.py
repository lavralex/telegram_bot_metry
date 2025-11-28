from typing import Optional, Dict, Any
from app.application.repositories.lead_repository import LeadRepository
from app.infrastructure.database.models import LeadStatus

class LeadService:
    def __init__(self, lead_repository: LeadRepository):
        self.lead_repository = lead_repository

    def create_lead_from_state(self, user_data: Dict[str, Any], state_data: Dict[str, Any]) -> Any:
        lead_data = {
            "user_id": user_data.get("id"),
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name"),
            "last_name": user_data.get("last_name"),
            "phone": state_data.get("phone"),
            "segment": state_data.get("segment", "unknown"),
            "utm_source": state_data.get("utm_source", "organic"),
            "budget": state_data.get("budget"),
            "timeline": state_data.get("timeline"),
            "management": state_data.get("management"),
            "experience": state_data.get("experience"),
            "user_path": state_data.get("user_path", []),
            "status": LeadStatus.NEW
        }
        
        return self.lead_repository.create_lead(lead_data)

    def get_daily_stats(self) -> Dict[str, Any]:
        today_leads = self.lead_repository.get_today_leads()
        leads_by_segment = self.lead_repository.get_leads_count_by_segment()
        
        return {
            "total_today": len(today_leads),
            "by_segment": leads_by_segment,
            "leads": today_leads
        }