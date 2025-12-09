import aiohttp
import json
from typing import Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Bitrix24Client:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session = None
        self.telegram_source_id = '79673596604'

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def create_lead(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает ЛИД в Bitrix24 с существующим источником 'ТГ бот'
        """
        try:
            utm_source = lead_data.get('utm_source', 'organic')
            segment = lead_data.get('segment', 'unknown')
            
            segment_names = {
                'investment': 'Недвижимость для инвестиций',
                'living': 'Недвижимость для жизни', 
                'manager': 'Связаться с менеджером',
                'analytics': 'Аналитика доходности',
                'unknown': 'Неизвестно'
            }
            segment_russian = segment_names.get(segment, segment)
            
            comments = self._format_comments_with_segment_notes(lead_data, segment_russian)
            
            first_name = lead_data.get('first_name', '')
            last_name = lead_data.get('last_name', '')
            full_name = f"{first_name} {last_name}".strip()
            title = f"{segment_russian} - {full_name}" if full_name else segment_russian
            
            bitrix_data = {
                'fields': {
                    'TITLE': title,
                    'NAME': first_name,
                    'LAST_NAME': last_name,
                    'SOURCE_ID': self.telegram_source_id,
                    'SOURCE_DESCRIPTION': f"Telegram Bot - UTM: {utm_source}",
                    'COMMENTS': comments,
                    'UTM_SOURCE': utm_source,
                    'UTM_MEDIUM': 'telegram',
                    'STATUS_ID': 'NEW',
                    'OPENED': 'Y'
                }
            }

            if lead_data.get('phone'):
                bitrix_data['fields']['PHONE'] = [{
                    'VALUE': lead_data.get('phone'), 
                    'VALUE_TYPE': 'WORK'
                }]

            logger.info(f"📤 Отправка ЛИДА в Bitrix24: {title}")
            logger.debug(f"Данные: {json.dumps(bitrix_data, ensure_ascii=False, indent=2)}")

            async with self.session.post(
                f"{self.webhook_url}/crm.lead.add",
                json=bitrix_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()
                logger.info(f"Ответ Bitrix24: {result}")

                if response.status == 200 and 'result' in result:
                    lead_id = result['result']
                    logger.info(f"✅ ЛИД создан, ID: {lead_id}")
                    return {'success': True, 'lead_id': lead_id}
                else:
                    error_msg = result.get('error_description', 'Unknown error')
                    logger.error(f"❌ Ошибка Bitrix24: {error_msg}")
                    return {'success': False, 'error': error_msg}

        except Exception as e:
            logger.error(f"❌ Ошибка при отправке в Bitrix24: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _format_comments_with_segment_notes(self, lead_data: Dict[str, Any], segment_russian: str) -> str:
        """Форматирует комментарий с пометками для разных сегментов"""
        parts = []
        
        parts.append(f"ЛИД ИЗ TELEGRAM БОТА - {segment_russian}")
        parts.append("=" * 50)
        
        parts.append("ОСНОВНЫЕ ДАННЫЕ:")
        parts.append(f"Username: @{lead_data.get('username', 'N/A')}")
        parts.append(f"Имя: {lead_data.get('first_name', '')} {lead_data.get('last_name', '')}")
        parts.append(f"Телефон: {lead_data.get('phone', 'не указан')}")
        
        parts.append("")
        parts.append("МЕТАДАННЫЕ:")
        parts.append(f"UTM: {lead_data.get('utm_source', 'organic')}")
        
        if lead_data.get('segment') == 'manager':
            experience = lead_data.get('experience', '')
            if experience == 'уже инвестировал(а)':
                parts.append("ПОМЕТКА: СТАРЫЙ КЛИЕНТ - уже инвестировал(а) с нами")
            else:
                parts.append("ПОМЕТКА: НОВЫЙ КЛИЕНТ - первый контакт")
        
        if lead_data.get('segment') == 'analytics':
            parts.append("ПОМЕТКА: ЗАПРОС АНАЛИТИКИ ДОХОДНОСТИ ЛОКАЦИЙ")
        
        parts.append("")
        
        if lead_data.get('budget'):
            parts.append(f"Бюджет: {lead_data.get('budget')}")
        if lead_data.get('timeline'):
            parts.append(f"Срок: {lead_data.get('timeline')}")
        if lead_data.get('management'):
            parts.append(f"Управление: {lead_data.get('management')}")
        if lead_data.get('experience') and lead_data.get('segment') != 'manager':
            parts.append(f"Опыт: {lead_data.get('experience')}")
        
        if lead_data.get('user_path'):
            parts.append("")
            parts.append("ПУТЬ ПОЛЬЗОВАТЕЛЯ:")
            parts.append("-" * 25)
            for i, step in enumerate(lead_data.get('user_path', []), 1):
                parts.append(f"{i}. {step}")
        
        parts.append("")
        parts.append("ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ:")
        parts.append(f"Источник: ТГ бот (ID: {self.telegram_source_id})")
        parts.append(f"Время создания: {lead_data.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(parts)

bitrix_client = None

async def init_bitrix_client(webhook_url: str):
    """Инициализирует клиент Bitrix24"""
    global bitrix_client
    if webhook_url:
        bitrix_client = Bitrix24Client(webhook_url)
        logger.info(f"Bitrix24 клиент инициализирован: {webhook_url}")
        logger.info(f"Используется источник: ТГ бот (ID: {bitrix_client.telegram_source_id})")
    else:
        logger.warning("Bitrix24 webhook URL не указан, интеграция отключена")

async def create_bitrix_lead(lead_data: Dict[str, Any]) -> Dict[str, Any]:
    """Создает ЛИД в Bitrix24 (обертка для глобального клиента)"""
    global bitrix_client
    if not bitrix_client:
        return {'success': False, 'error': 'Bitrix24 клиент не инициализирован'}
    
    if 'timestamp' not in lead_data:
        lead_data['timestamp'] = datetime.now()
    
    async with bitrix_client as client:
        return await client.create_lead(lead_data)