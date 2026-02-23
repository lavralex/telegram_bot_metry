from __future__ import annotations

from typing import Any, Dict, Tuple, Optional

from app.application.repositories.lead_repository import LeadRepository
from app.infrastructure.database.models import Lead, LeadStatus


class LeadService:
    """Сервис работы с лидами в БД + сборка полей для Bitrix.

    Правило (текущая логика продукта):
    - /start НЕ создает лиды (только UTM/состояние пользователя)
    - сообщение в чате создает лид ТОЛЬКО если у пользователя ещё нет ни одного лида
      (иначе продолжает последний и обновляет его данными из state)
    - оставление телефона (contact) ВСЕГДА создает НОВЫЙ лид
    """

    def __init__(self, lead_repository: LeadRepository):
        self.lead_repository = lead_repository

    def ensure_minimal_lead_from_state(
        self,
        user_data: Dict[str, Any],
        state_data: Dict[str, Any],
    ) -> Tuple[Lead, Dict[str, Any]]:
        """Для сообщений: продолжить последний лид, или создать первый."""
        user_id = self._must_user_id(user_data)
        normalized_state = self._normalize_state(state_data)

        lead = self._pick_latest_lead(user_id)

        if lead:
            lead = self.lead_repository.update_lead_from_state(lead.id, normalized_state) or lead
        else:
            lead = self._create_lead(user_data, normalized_state)

        return lead, self._build_bitrix_fields_from_lead(lead)

    def create_new_lead_from_state(
        self,
        user_data: Dict[str, Any],
        state_data: Dict[str, Any],
    ) -> Tuple[Lead, Dict[str, Any]]:
        """Для contact/телефона: всегда создать новый лид."""
        normalized_state = self._normalize_state(state_data)
        lead = self._create_lead(user_data, normalized_state)
        return lead, self._build_bitrix_fields_from_lead(lead)

    def build_bitrix_fields(self, lead: Lead) -> Dict[str, Any]:
        return self._build_bitrix_fields_from_lead(lead)

    @staticmethod
    def _must_user_id(user_data: Dict[str, Any]) -> int:
        user_id = user_data.get("user_id") or user_data.get("id")
        if not user_id:
            raise ValueError("user_id не найден в user_data")
        return int(user_id)

    @staticmethod
    def _normalize_state(state_data: Dict[str, Any]) -> Dict[str, Any]:
        s = dict(state_data or {})
        s.setdefault("utm_source", "organic")
        s.setdefault("user_path", [])
        return s

    def _pick_latest_lead(self, user_id: int) -> Optional[Lead]:
        return self.lead_repository.get_latest_lead_by_user_id(user_id)

    def _create_lead(self, user_data: Dict[str, Any], normalized_state: Dict[str, Any]) -> Lead:
        user_id = self._must_user_id(user_data)

        username = user_data.get("username") or ""
        first_name = user_data.get("first_name") or ""
        last_name = user_data.get("last_name") or ""

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

        return self.lead_repository.create_lead(lead_data)

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

        comments = "\n".join(parts) if parts else "Лид из Telegram."

        title_user = f"@{username}" if username else f"tg:{lead.user_id}"
        title_seg = segment if segment else "без сегмента"

        fields: Dict[str, Any] = {
            "TITLE": f"Telegram {title_user} — {title_seg}",
            "NAME": first_name or (username if username else ""),
            "LAST_NAME": last_name or "",
            "COMMENTS": comments,
        }

        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]

        return fields
