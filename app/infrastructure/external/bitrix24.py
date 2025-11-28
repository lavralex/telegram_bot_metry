import aiohttp
import json
from typing import Dict, Any, Optional
import logging

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

    async def create_contact(self, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает контакт в Bitrix24 с существующим источником 'ТГ бот'
        """
        try:
            utm_source = contact_data.get('utm_source', 'organic')
            
            # Подготавливаем данные для Bitrix24
            bitrix_data = {
                'fields': {
                    'TITLE': f"Контакт из Telegram: {contact_data.get('first_name', '')} {contact_data.get('last_name', '')}",
                    'NAME': contact_data.get('first_name', ''),
                    'LAST_NAME': contact_data.get('last_name', ''),
                    'SOURCE_ID': self.telegram_source_id,
                    'SOURCE_DESCRIPTION': f"UTM: {utm_source}",
                    'COMMENTS': self._format_comments(contact_data)
                }
            }

            # Добавляем телефон если есть
            if contact_data.get('phone'):
                bitrix_data['fields']['PHONE'] = [{
                    'VALUE': contact_data.get('phone'), 
                    'VALUE_TYPE': 'WORK'
                }]

            logger.info(f"Отправка контакта в Bitrix24 с источником ID: {self.telegram_source_id}")

            async with self.session.post(
                f"{self.webhook_url}/crm.contact.add",
                json=bitrix_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()
                
                # Безопасное логирование ответа
                if response.status == 200 and 'result' in result:
                    logger.info(f"✅ Контакт создан в Bitrix24, ID: {result['result']}")
                    return {'success': True, 'contact_id': result['result']}
                else:
                    error_msg = result.get('error_description', 'Unknown error')
                    logger.error(f"❌ Ошибка Bitrix24: {error_msg}")
                    return {'success': False, 'error': error_msg}

        except Exception as e:
            logger.error(f"❌ Ошибка при отправке в Bitrix24: {e}")
            return {'success': False, 'error': str(e)}

    def _format_comments(self, contact_data: Dict[str, Any]) -> str:
        """Форматирует комментарий для Bitrix24"""
        comments = [
            "📋 ДАННЫЕ ИЗ TELEGRAM БОТА",
            "=" * 35,
            f"👤 User ID: {contact_data.get('id', contact_data.get('user_id', 'N/A'))}",
            f"🔗 Username: @{contact_data.get('username', 'N/A')}",
            f"🏷️ UTM Source: {contact_data.get('utm_source', 'organic')}",
            f"📊 Сегмент: {contact_data.get('segment', 'unknown')}",
            "",  # Пустая строка для разделения
        ]

        # Добавляем дополнительные данные в зависимости от сегмента
        additional_data = []
        if contact_data.get('budget'):
            additional_data.append(f"💰 Бюджет: {contact_data.get('budget')}")
        if contact_data.get('timeline'):
            additional_data.append(f"⏰ Срок: {contact_data.get('timeline')}")
        if contact_data.get('management'):
            additional_data.append(f"🏢 Управление: {contact_data.get('management')}")
        if contact_data.get('experience'):
            additional_data.append(f"💼 Опыт: {contact_data.get('experience')}")
        
        if additional_data:
            comments.extend(additional_data)
            comments.append("")  # Пустая строка для разделения

        # Путь пользователя
        if contact_data.get('user_path'):
            comments.append("🛣️ ПУТЬ ПОЛЬЗОВАТЕЛЯ:")
            comments.append("-" * 25)
            for i, step in enumerate(contact_data.get('user_path', []), 1):
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

async def create_bitrix_contact(contact_data: Dict[str, Any]) -> Dict[str, Any]:
    """Создает контакт в Bitrix24 (обертка для глобального клиента)"""
    global bitrix_client
    if not bitrix_client:
        return {'success': False, 'error': 'Bitrix24 клиент не инициализирован'}
    
    async with bitrix_client as client:
        return await client.create_contact(contact_data)