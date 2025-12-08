from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputFile, FSInputFile, BufferedInputFile
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import pandas as pd
from io import BytesIO
import asyncio
import re
import os

from app.core.config import config
from app.core.dependencies import get_lead_repository, get_link_click_repository
from app.infrastructure.database.models import Lead, Broadcast
from app.core.database import SessionLocal
from app.application.services.broadcast_service import broadcast_service

admin_router = Router()

BROADCAST_STATUS_EMOJI = {
    'draft': "📝",
    'scheduled': "⏰", 
    'sent': "✅",
    'cancelled': "❌"
}

# Фильтр для проверки админа
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# Состояния для создания рассылки
class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    waiting_for_time = State()

# Команда для получения ID пользователя

@admin_router.message(Command("check_broadcasts"))
async def admin_check_broadcasts(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return
    
    if broadcast_service:
        await broadcast_service.check_scheduled_broadcasts()
        await message.answer("✅ Проверка рассылок выполнена")
    else:
        await message.answer("❌ Сервис рассылок не запущен")


@admin_router.message(Command("myid"))
async def get_my_id(message: Message):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "не указан"
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    
    await message.answer(
        f"👤 **ВАШИ ДАННЫЕ:**\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"📛 Имя: {first_name} {last_name}\n"
        f"🔗 Username: {username}\n\n"
        f"💡 *Скопируйте ID и добавьте в файл .env*"
    )

# Статистика
@admin_router.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    click_repo = get_link_click_repository()
    
    try:
        # Общая статистика
        today_leads = lead_repo.get_today_leads()
        total_leads = len(today_leads)
        total_clicks = click_repo.get_clicks_count()
        
        # Статистика по сегментам
        leads_by_segment = lead_repo.get_leads_count_by_segment()
        
        # Популярные UTM
        popular_utm = click_repo.get_popular_utm_sources(5)
        
        # Конверсия (упрощенная)
        conversion = (total_leads / total_clicks * 100) if total_clicks > 0 else 0
        
        stats_text = (
            "📊 **СТАТИСТИКА ЗА СЕГОДНЯ**\n\n"
            f"🎯 Лидов: **{total_leads}**\n"
            f"🖱️ Переходов: **{total_clicks}**\n"
            f"📈 Конверсия: **{conversion:.1f}%**\n\n"
            "**Лиды по сегментам:**\n"
        )
        
        for segment, count in leads_by_segment.items():
            stats_text += f"  • {segment}: {count}\n"
        
        stats_text += "\n**Топ UTM меток:**\n"
        for utm in popular_utm:
            leads_count = lead_repo.db.query(Lead).filter(Lead.utm_source == utm['utm_source']).count()
            stats_text += f"  • {utm['utm_source']}: {utm['clicks']} кликов, {leads_count} лидов\n"
        
        await message.answer(stats_text)
    finally:
        lead_repo.db.close()
        click_repo.db.close()

# Детальная статистика по UTM
@admin_router.message(Command("utm_stats"))
async def admin_utm_stats(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    click_repo = get_link_click_repository()
    
    args = command.args
    if not args:
        await message.answer("Укажите UTM метку: /utm_stats utm_invest")
        return
    
    utm_source = args.strip()
    
    try:
        clicks = click_repo.get_clicks_count(utm_source)
        leads = lead_repo.db.query(Lead).filter(Lead.utm_source == utm_source).all()
        
        stats_text = (
            f"📊 **СТАТИСТИКА ПО UTM:** {utm_source}\n\n"
            f"🖱️ Кликов: **{clicks}**\n"
            f"🎯 Лидов: **{len(leads)}**\n"
            f"📈 Конверсия: **{(len(leads)/clicks*100 if clicks > 0 else 0):.1f}%**\n\n"
        )
        
        if leads:
            stats_text += "**Последние лиды:**\n"
            for lead in leads[:5]:  # Последние 5 лидов
                stats_text += f"  • {lead.first_name} {lead.last_name} - {lead.phone} ({lead.created_at.strftime('%H:%M')})\n"
        
        await message.answer(stats_text)
    finally:
        lead_repo.db.close()
        click_repo.db.close()

# Просмотр лидов
@admin_router.message(Command("leads"))
async def admin_leads(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    
    try:
        # Проверяем есть ли аргумент для фильтрации по сегменту
        args = command.args
        if args:
            today_leads = lead_repo.get_leads_by_segment(args)
        else:
            today_leads = lead_repo.get_today_leads()
        
        if not today_leads:
            segment_text = f" ({args})" if args else ""
            await message.answer(f"📭 Лидов за сегодня{segment_text} нет")
            return
        
        segment_text = f" ({args})" if args else ""
        leads_text = f"🎯 **ПОСЛЕДНИЕ ЛИДЫ{segment_text}**\n\n"
        
        for lead in today_leads[:10]:  # Последние 10 лидов
            phone_display = lead.phone if lead.phone else "❌ не указан"
            budget_display = lead.budget if lead.budget else "не указан"
            
            leads_text += (
                f"👤 **{lead.first_name} {lead.last_name or ''}**\n"
                f"📞 {phone_display}\n"
                f"🏷️ {lead.segment} | {lead.utm_source}\n"
                f"💰 {budget_display}\n"
                f"⏰ {lead.created_at.strftime('%H:%M')}\n"
                f"---\n"
            )
        
        await message.answer(leads_text)
    finally:
        lead_repo.db.close()

# Генератор UTM ссылок
@admin_router.message(Command("links"))
async def admin_links(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    click_repo = get_link_click_repository()
    lead_repo = get_lead_repository()
    
    bot_username = (await message.bot.get_me()).username
    
    try:
        links_text = "🔗 **UTM ССЫЛКИ ДЛЯ РЕКЛАМЫ**\n\n"
        
        # === ИСПОЛЬЗУЕМ английские UTM ключи для ссылок ===
        for utm_key, utm_name in config.UTM_SEGMENTS.items():
            clicks = click_repo.get_clicks_count(utm_key)
            leads_count = lead_repo.db.query(Lead).filter(Lead.utm_source == utm_key).count()
            conversion = (leads_count / clicks * 100) if clicks > 0 else 0
            
            link = f"https://t.me/{bot_username}?start={utm_key}"
            
            links_text += (
                f"**{utm_name}**\n"
                f"`{link}`\n"
                f"🖱️ Кликов: {clicks} | 🎯 Лидов: {leads_count} | 📈 {conversion:.1f}%\n\n"
            )
        
        links_text += "💡 *Нажмите на ссылку чтобы скопировать*"
        
        await message.answer(links_text)
    finally:
        click_repo.db.close()
        lead_repo.db.close()

# Экспорт данных
@admin_router.message(Command("export"))
async def admin_export(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    
    try:
        # Проверяем аргументы для фильтрации
        args = command.args
        if args and args in ['today', 'all']:
            if args == 'today':
                all_leads = lead_repo.get_today_leads()
                filename_suffix = "today"
            else:  # 'all'
                all_leads = lead_repo.db.query(Lead).all()
                filename_suffix = "all"
        else:
            # По умолчанию - все лиды
            all_leads = lead_repo.db.query(Lead).all()
            filename_suffix = "all"
        
        if not all_leads:
            await message.answer("📭 Нет данных для экспорта")
            return
        
        # Создаем DataFrame
        data = []
        for lead in all_leads:
            data.append({
                'ID': lead.id,
                'Дата': lead.created_at.strftime('%Y-%m-%d %H:%M'),
                'Имя': lead.first_name,
                'Фамилия': lead.last_name,
                'Username': f"@{lead.username}" if lead.username else "",
                'Телефон': lead.phone,
                'Сегмент': lead.segment,
                'UTM': lead.utm_source,
                'Бюджет': lead.budget,
                'Срок': lead.timeline,
                'Управление': lead.management,
                'Опыт': lead.experience,
                'Статус': lead.status
            })
        
        df = pd.DataFrame(data)
        
        # Создаем Excel файл в памяти
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Лиды', index=False)
        
        output.seek(0)
        excel_data = output.getvalue()
        
        # Используем BufferedInputFile для отправки
        filename = f"leads_export_{filename_suffix}_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        
        await message.answer_document(
            document=BufferedInputFile(excel_data, filename=filename),
            caption=f"📊 Экспорт лидов ({filename_suffix}) - {len(all_leads)} записей"
        )
    finally:
        lead_repo.db.close()

# Создание рассылки
@admin_router.message(Command("broadcast"))
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    await message.answer(
        "📢 **СОЗДАНИЕ РАССЫЛКИ**\n\n"
        "Отправьте текст сообщения для рассылки:"
    )
    await state.set_state(BroadcastStates.waiting_for_text)

@admin_router.message(BroadcastStates.waiting_for_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    # Проверяем что message.text не None
    if not message.text:
        await message.answer("❌ Пожалуйста, отправьте текстовое сообщение:")
        return
        
    if len(message.text) > 4000:
        await message.answer("❌ Текст слишком длинный (максимум 4000 символов). Отправьте более короткий текст:")
        return
        
    await state.update_data(text=message.text)
    
    await message.answer(
        "📷 Хотите добавить изображение?\n"
        "Отправьте фото или нажмите /skip чтобы пропустить"
    )
    await state.set_state(BroadcastStates.waiting_for_photo)

@admin_router.message(BroadcastStates.waiting_for_photo, F.photo)
async def process_broadcast_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    
    await message.answer(
        "⏰ Когда отправить рассылку?\n\n"
        "Варианты:\n"
        "• `now` - отправить сейчас\n"
        "• `14:30` - сегодня в указанное время\n" 
        "• `01.12.2024 14:30` - конкретная дата и время\n"
        "• `+2 hours` - через 2 часа\n"
        "• `tomorrow 10:00` - завтра в 10:00\n\n"
        "💡 *Время указывается по Москве*"
    )
    await state.set_state(BroadcastStates.waiting_for_time)

@admin_router.message(BroadcastStates.waiting_for_photo, Command("skip"))
async def process_broadcast_skip_photo(message: Message, state: FSMContext):
    await state.update_data(photo=None)
    
    await message.answer(
        "⏰ Когда отправить рассылку?\n\n"
        "Варианты:\n"
        "• `now` - отправить сейчас\n"
        "• `14:30` - сегодня в указанное время\n"
        "• `01.12.2024 14:30` - конкретная дата и время\n"
        "• `+2 hours` - через 2 часа\n"
        "• `tomorrow 10:00` - завтра в 10:00\n\n"
        "💡 *Время указывается по Москве*"
    )
    await state.set_state(BroadcastStates.waiting_for_time)

@admin_router.message(BroadcastStates.waiting_for_time)
async def process_broadcast_time(message: Message, state: FSMContext):
    # Проверяем что message.text не None
    if not message.text:
        await message.answer("❌ Пожалуйста, укажите время:")
        return
        
    time_input = message.text.strip().lower()
    data = await state.get_data()
    
    try:
        send_time = parse_time_input(time_input)
        
        # Показываем пользователю время по Москве
        moscow_time = send_time + timedelta(hours=3)
        
        if send_time <= datetime.utcnow():
            # Отправляем сразу
            success, failed = await send_broadcast(message.bot, data['text'], data.get('photo'))
            status = f"✅ Отправлено сразу\nУспешно: {success}, Не удалось: {failed}"
        else:
            # Сохраняем в базу для отложенной отправки
            db = SessionLocal()
            broadcast = Broadcast(
                title=f"Рассылка от {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                message_text=data['text'],
                photo_url=data.get('photo'),
                scheduled_time=send_time,
                status="scheduled",
                created_by=message.from_user.id
            )
            db.add(broadcast)
            db.commit()
            db.close()
            
            status = f"⏰ Запланировано на {moscow_time.strftime('%d.%m.%Y %H:%M')} по Москве"
        
        await message.answer(
            f"📢 **РАССЫЛКА СОЗДАНА**\n\n"
            f"{status}\n"
            f"Текст: {data['text'][:100]}..."
        )
        
    except ValueError as e:
        await message.answer(f"❌ {str(e)}\nПопробуйте снова:")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        return
    
    await state.clear()

def parse_time_input(time_input: str) -> datetime:
    """Парсит ввод времени пользователя с поправкой на +3 часа (Москва -> UTC)"""
    now_utc = datetime.utcnow()
    now_moscow = now_utc + timedelta(hours=3)  # Текущее время по Москве
    
    if time_input == 'now':
        return now_utc
    
    # Относительное время: +2 hours, +30 minutes
    relative_match = re.match(r'\+(\d+)\s*(hour|hours|minute|minutes|hr|min)', time_input)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        
        if unit in ['hour', 'hours', 'hr']:
            return now_utc + timedelta(hours=amount)
        elif unit in ['minute', 'minutes', 'min']:
            return now_utc + timedelta(minutes=amount)
    
    # Завтра в указанное время: tomorrow 10:00
    if time_input.startswith('tomorrow'):
        time_part = time_input.replace('tomorrow', '').strip()
        if not time_part:
            time_part = '10:00'
        time_obj = datetime.strptime(time_part, '%H:%M').time()
        # Создаем datetime на завтра в указанное время по Москве
        result_moscow = datetime.combine(now_moscow.date() + timedelta(days=1), time_obj)
        # Конвертируем в UTC (вычитаем 3 часа)
        result_utc = result_moscow - timedelta(hours=3)
        return result_utc
    
    # Попробуем разные форматы дат
    formats = [
        '%d.%m.%Y %H:%M',    # 01.12.2024 14:30
        '%Y-%m-%d %H:%M',    # 2024-12-01 14:30
        '%H:%M',             # 14:30 (сегодня)
        '%d.%m %H:%M',       # 01.12 14:30 (текущий год)
    ]
    
    for fmt in formats:
        try:
            if fmt == '%H:%M':
                # Для времени без даты - парсим как московское время сегодня
                time_obj = datetime.strptime(time_input, fmt).time()
                result_moscow = datetime.combine(now_moscow.date(), time_obj)
                
                # Если время уже прошло сегодня по Москве, планируем на завтра
                if result_moscow < now_moscow:
                    result_moscow += timedelta(days=1)
                
                # Конвертируем в UTC (вычитаем 3 часа)
                result_utc = result_moscow - timedelta(hours=3)
                return result_utc
            else:
                # Для дат с временем - парсим как московское время и конвертируем в UTC
                naive_dt = datetime.strptime(time_input, fmt)
                # Предполагаем, что пользователь вводит московское время
                result_utc = naive_dt - timedelta(hours=3)
                return result_utc
        except ValueError:
            continue
    
    raise ValueError("Не удалось распознать время. Используйте формат: 14:30 или 01.12.2024 14:30")

async def send_broadcast(bot, text: str, photo: str = None) -> tuple[int, int]:
    """Отправка рассылки всем пользователям из базы"""
    lead_repo = get_lead_repository()
    try:
        users = set(lead.user_id for lead in lead_repo.db.query(Lead).all())
        
        success = 0
        failed = 0
        
        for user_id in users:
            try:
                if photo:
                    await bot.send_photo(user_id, photo, caption=text)
                else:
                    await bot.send_message(user_id, text)
                success += 1
                await asyncio.sleep(0.05)  # Чтобы не превысить лимиты Telegram (30 сообщений/секунду)
            except Exception as e:
                print(f"❌ Ошибка отправки пользователю {user_id}: {e}")
                failed += 1
        
        return success, failed
    finally:
        lead_repo.db.close()

# Просмотр запланированных рассылок
@admin_router.message(Command("broadcasts"))
async def admin_broadcasts(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    db = SessionLocal()
    try:
        broadcasts = db.query(Broadcast).order_by(Broadcast.scheduled_time.desc()).limit(10).all()
        
        if not broadcasts:
            await message.answer("📭 Нет запланированных рассылок")
            return
        
        broadcasts_text = "📢 **ЗАПЛАНИРОВАННЫЕ РАССЫЛКИ**\n\n"
        
        for broadcast in broadcasts:
            status_emoji = BROADCAST_STATUS_EMOJI.get(broadcast.status, "❓")
            
            # Показываем время по Москве (добавляем 3 часа)
            moscow_time = broadcast.scheduled_time + timedelta(hours=3)
            
            broadcasts_text += (
                f"{status_emoji} **{broadcast.title}**\n"
                f"⏰ {moscow_time.strftime('%d.%m.%Y %H:%M')} по Москве\n"
                f"📝 {broadcast.message_text[:50]}...\n"
                f"📊 Статус: {broadcast.status}\n"
                f"---\n"
            )
        
        await message.answer(broadcasts_text)
    finally:
        db.close()

# Быстрая рассылка (без состояний)
@admin_router.message(Command("quick_send"))
async def admin_quick_send(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    # Проверяем что есть аргументы
    if not command.args:
        await message.answer(
            "❌ Укажите текст для рассылки:\n"
            "Пример: `/quick_send Привет! У нас новые предложения`"
        )
        return
    
    text = command.args
    if len(text) > 4000:
        await message.answer("❌ Текст слишком длинный (максимум 4000 символов)")
        return
    
    # Сразу отправляем
    success, failed = await send_broadcast(message.bot, text)
    
    await message.answer(
        f"📢 **БЫСТРАЯ РАССЫЛКА ОТПРАВЛЕНА**\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}\n"
        f"📝 Текст: {text[:100]}..."
    )

# Помощь по админ-командам
@admin_router.message(Command("admin_help"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    help_text = (
        "🛠 **АДМИН-ПАНЕЛЬ - КОМАНДЫ**\n\n"
        
        "📊 **Статистика:**\n"
        "• /stats - общая статистика за сегодня\n"
        "• /utm_stats [utm] - статистика по конкретной UTM\n"
        "• /leads [сегмент] - просмотр лидов (опционально по сегменту)\n\n"
        
        "🔗 **Ссылки:**\n"  
        "• /links - генератор UTM ссылок с статистикой\n\n"
        
        "📁 **Экспорт:**\n"
        "• /export - экспорт всех лидов в Excel\n"
        "• /export today - экспорт только сегодняшних лидов\n"
        "• /export all - экспорт всех лидов (по умолчанию)\n\n"
        
        "📢 **Рассылки:**\n"
        "• /broadcast - создание рассылки (текст + фото + время)\n"
        "• /broadcasts - просмотр запланированных рассылок\n"
        "• /quick_send [текст] - быстрая рассылка (только текст)\n\n"
        
        "💬 **Переписка с пользователями:**\n"
        "• /unread - непрочитанные сообщения\n"
        "• /toggle_chat - включить/выключить переписку\n\n"
        
        "🆔 **Утилиты:**\n"
        "• /myid - узнать свой Telegram ID\n\n"
        
        "💡 **Примеры:**\n"
        "• /leads investment\n"
        "• /utm_stats utm_invest\n"
        "• /quick_send Привет! У нас новые предложения\n"
        "• /export today\n\n"
        "⏰ *Время в рассылках указывается по Москве*"
    )
    
    await message.answer(help_text)