import aiohttp
import json
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class Bitrix24Client:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session = None
        self.telegram_source_id = '79673596604'  # === ИСПОЛЬЗУЕМ СУЩЕСТВУЮЩИЙ ИСТОЧНИК ===

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def create_lead(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает лид в Bitrix24 с существующим источником 'ТГ бот'
        """
        try:
            utm_source = lead_data.get('utm_source', 'organic')
            
            # Подготавливаем данные для Bitrix24
            bitrix_data = {
                'fields': {
                    'TITLE': f"Лид из Telegram: {lead_data.get('first_name', '')} {lead_data.get('last_name', '')}",
                    'NAME': lead_data.get('first_name', ''),
                    'LAST_NAME': lead_data.get('last_name', ''),
                    'SOURCE_ID': self.telegram_source_id,  # Используем существующий источник
                    'SOURCE_DESCRIPTION': f"UTM: {utm_source}",
                    'COMMENTS': self._format_comments(lead_data)
                }
            }

            # Добавляем телефон если есть
            if lead_data.get('phone'):
                bitrix_data['fields']['PHONE'] = [{
                    'VALUE': lead_data.get('phone'), 
                    'VALUE_TYPE': 'WORK'
                }]

            logger.info(f"Отправка лида в Bitrix24 с источником ID: {self.telegram_source_id}")

            async with self.session.post(
                f"{self.webhook_url}/crm.lead.add",
                json=bitrix_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()
                logger.info(f"Ответ от Bitrix24: {result}")

                if response.status == 200 and 'result' in result:
                    return {'success': True, 'lead_id': result['result']}
                else:
                    error_msg = result.get('error_description', 'Unknown error')
                    logger.error(f"Ошибка Bitrix24: {error_msg}")
                    return {'success': False, 'error': error_msg}

        except Exception as e:
            logger.error(f"Ошибка при отправке в Bitrix24: {e}")
            return {'success': False, 'error': str(e)}

    def _format_comments(self, lead_data: Dict[str, Any]) -> str:
        """Форматирует комментарий для Bitrix24"""
        comments = [
            "📋 ДАННЫЕ ИЗ TELEGRAM БОТА",
            "=" * 35,
            f"👤 User ID: {lead_data.get('id', lead_data.get('user_id', 'N/A'))}",
            f"🔗 Username: @{lead_data.get('username', 'N/A')}",
            f"🏷️ UTM Source: {lead_data.get('utm_source', 'organic')}",
            f"📊 Сегмент: {lead_data.get('segment', 'unknown')}",
            f"📞 Телефон: {lead_data.get('phone', 'не указан')}",
            "",  # Пустая строка для разделения
        ]

        # Добавляем дополнительные данные в зависимости от сегмента
        additional_data = []
        if lead_data.get('budget'):
            additional_data.append(f"💰 Бюджет: {lead_data.get('budget')}")
        if lead_data.get('timeline'):
            additional_data.append(f"⏰ Срок: {lead_data.get('timeline')}")
        if lead_data.get('management'):
            additional_data.append(f"🏢 Управление: {lead_data.get('management')}")
        if lead_data.get('experience'):
            additional_data.append(f"💼 Опыт: {lead_data.get('experience')}")
        
        if additional_data:
            comments.extend(additional_data)
            comments.append("")  # Пустая строка для разделения

        # Путь пользователя
        if lead_data.get('user_path'):
            comments.append("🛣️ ПУТЬ ПОЛЬЗОВАТЕЛЯ:")
            comments.append("-" * 25)
            for i, step in enumerate(lead_data.get('user_path', []), 1):
                comments.append(f"{i}. {step}")

        return "\n".join(comments)

# Глобальный клиент Bitrix24
bitrix_client = None

async def init_bitrix_client(webhook_url: str):
    """Инициализирует клиент Bitrix24"""
    global bitrix_client
    if webhook_url:
        bitrix_client = Bitrix24Client(webhook_url)
        logger.info(f"✅ Bitrix24 клиент инициализирован: {webhook_url}")
        logger.info(f"📝 Используется источник: ТГ бот (ID: {bitrix_client.telegram_source_id})")
    else:
        logger.warning("⚠️ Bitrix24 webhook URL не указан, интеграция отключена")

async def create_bitrix_lead(lead_data: Dict[str, Any]) -> Dict[str, Any]:
    """Создает лид в Bitrix24 (обертка для глобального клиента)"""
    global bitrix_client
    if not bitrix_client:
        return {'success': False, 'error': 'Bitrix24 клиент не инициализирован'}
    
    async with bitrix_client as client:
        return await client.create_lead(lead_data)