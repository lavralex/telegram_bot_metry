from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_contact_keyboard(segment: str = None):
    buttons = [
        [InlineKeyboardButton(
            text="📞 Поделиться контактом", 
            callback_data="share_contact"
        )],
    ]
    
    # Динамическая кнопка назад в зависимости от сегмента
    back_data = "back_to_main"
    if segment == "investment":
        back_data = "back_to_management_investment"
    elif segment == "living":
        back_data = "back_to_timeline_living"
    elif segment == "manager":
        back_data = "back_to_experience"
    elif segment == "analytics":
        back_data = "back_to_main"
        
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_policy_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика обработки персональных данных", url="https://metry.group/policy/")]
        ]
    )

def get_subscribe_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на Telegram-канал", url="https://t.me/metrigroup")]
        ]
    )