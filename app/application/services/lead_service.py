from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Tuple, Optional

from app.application.repositories.lead_repository import LeadRepository
from app.infrastructure.database.models import Lead, LeadStatus


class LeadService:
    """
    Ensure-lead сервис:
    - не плодим лиды на каждое сообщение
    - держим "текущий" лид пользователя и обновляем его данными из state
    """

    def __init__(self, lead_repository: LeadRepository):
        self.lead_repository = lead_repository

    def ensure_minimal_lead_from_state(
        self,
        user_data: Dict[str, Any],
        state_data: Dict[str, Any],
    ) -> Tuple[Lead, Dict[str, Any]]:
        return self._ensure_lead_common(user_data, state_data)

    def ensure_full_lead_from_state(
        self,
        user_data: Dict[str, Any],
        state_data: Dict[str, Any],
    ) -> Tuple[Lead, Dict[str, Any]]:
        return self._ensure_lead_common(user_data, state_data)

    def _pick_existing_lead(self, user_id: int) -> Optional[Lead]:
        """
        Выбираем лид, который будем продолжать.
        Сейчас: берём последний, если он достаточно свежий и ещё NEW.
        """
        lead = self.lead_repository.get_latest_lead_by_user_id(user_id)
        if not lead:
            return None

        if getattr(lead, "status", None) and str(lead.status) != LeadStatus.NEW.value:
            return None

        created_at = getattr(lead, "created_at", None)
        if created_at and isinstance(created_at, datetime):
            if created_at < datetime.utcnow() - timedelta(days=14):
                return None

        return lead

    def _ensure_lead_common(self, user_data: Dict[str, Any], state_data: Dict[str, Any]) -> Tuple[Lead, Dict[str, Any]]:
        user_id = user_data.get("user_id") or user_data.get("id")
        if not user_id:
            raise ValueError("user_id не найден в user_data")

        username = user_data.get("username") or ""
        first_name = user_data.get("first_name") or ""
        last_name = user_data.get("last_name") or ""

        normalized_state = dict(state_data or {})
        normalized_state.setdefault("utm_source", "organic")
        normalized_state.setdefault("user_path", [])

        existing = self._pick_existing_lead(int(user_id))

        if existing:
            lead = self.lead_repository.update_lead_from_state(existing.id, normalized_state) or existing
        else:
            lead_data = {
                "user_id": int(user_id),
                "username": username or None,
                "first_name": first_name or None,
                "last_name": last_name or None,
                "phone": (normalized_state.get("phone") or "").strip() or None,
                "segment": (normalized_state.get("segment") or "").strip() or None,
                "utm_source": (normalized_state.get("utm_source") or "").strip() or "organic",
                "budget": (normalized_state.get("budget") or "").strip() or None,
                "timeline": (normalized_state.get("timeline") or "").strip() or None,
                "management": (normalized_state.get("management") or "").strip() or None,
                "experience": (normalized_state.get("experience") or "").strip() or None,
                "user_path": normalized_state.get("user_path") or [],
                "status": LeadStatus.NEW.value,
            }
            lead = self.lead_repository.create_lead(lead_data)

        bitrix_fields = self._build_bitrix_fields_from_lead(lead)
        return lead, bitrix_fields

    def _build_bitrix_fields_from_lead(self, lead: Lead) -> Dict[str, Any]:
        segment = (getattr(lead, "segment", None) or "").strip() or None
        utm_source = (getattr(lead, "utm_source", None) or "").strip() or "organic"
        phone = (getattr(lead, "phone", None) or "").strip() or None

        budget = (getattr(lead, "budget", None) or "").strip() or None
        timeline = (getattr(lead, "timeline", None) or "").strip() or None
        management = (getattr(lead, "management", None) or "").strip() or None
        experience = (getattr(lead, "experience", None) or "").strip() or None
        user_path = getattr(lead, "user_path", None) or []

        username = getattr(lead, "username", None) or ""
        first_name = getattr(lead, "first_name", None) or ""
        last_name = getattr(lead, "last_name", None) or ""

        parts = []
        if segment:
            parts.append(f"Сегмент: {segment}")
        if utm_source:
            parts.append(f"UTM: {utm_source}")
        if budget:
            parts.append(f"Бюджет: {budget}")
        if timeline:
            parts.append(f"Срок: {timeline}")
        if management:
            parts.append(f"Управление: {management}")
        if experience:
            parts.append(f"Опыт: {experience}")
        if user_path:
            parts.append(f"Путь: {' → '.join(map(str, user_path))}")

        comments = "\n".join(parts) if parts else "Лид из Telegram (минимальный)."

        title_user = f"@{username}" if username else f"tg:{lead.user_id}"
        title_seg = segment if segment else "без сегмента"
        title = f"Telegram {title_user} — {title_seg}"

        fields: Dict[str, Any] = {
            "TITLE": title,
            "NAME": first_name or (username if username else ""),
            "LAST_NAME": last_name or "",
            "COMMENTS": comments,
        }

        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]

        return fields
    
    def build_bitrix_fields(self, lead: Lead) -> Dict[str, Any]:
        """
        Публичная обёртка для сборки полей Bitrix из уже существующего лида.
        Удобно для contact.py и любых мест, где нельзя/не нужно создавать новый Lead.
        """
        return self._build_bitrix_fields_from_lead(lead)
