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
import logging

logger = logging.getLogger(__name__)

from app.core.config import config
from app.core.dependencies import get_lead_repository, get_link_click_repository, get_user_repository
from app.infrastructure.database.models import Lead, Broadcast, LinkClick
from app.core.database import SessionLocal
from app.application.services.broadcast_service import broadcast_service

admin_router = Router()

BROADCAST_STATUS_EMOJI = {
    'draft': "📝",
    'scheduled': "⏰", 
    'sent': "✅",
    'cancelled': "❌"
}

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    waiting_for_time = State()

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

@admin_router.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    click_repo = get_link_click_repository()
    
    try:
        today_leads = lead_repo.get_today_leads()
        total_leads = len(today_leads)
        total_clicks = click_repo.get_clicks_count()
        leads_by_segment = lead_repo.get_leads_count_by_segment()
        popular_utm = click_repo.get_popular_utm_sources(5)
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
            for lead in leads[:5]:
                stats_text += f"  • {lead.first_name} {lead.last_name} - {lead.phone} ({lead.created_at.strftime('%H:%M')})\n"
        
        await message.answer(stats_text)
    finally:
        lead_repo.db.close()
        click_repo.db.close()

@admin_router.message(Command("leads"))
async def admin_leads(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    
    try:
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
        
        for lead in today_leads[:10]:
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

@admin_router.message(Command("export"))
async def admin_export(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    lead_repo = get_lead_repository()
    
    try:
        args = command.args
        if args and args in ['today', 'all']:
            if args == 'today':
                all_leads = lead_repo.get_today_leads()
                filename_suffix = "today"
            else:
                all_leads = lead_repo.db.query(Lead).all()
                filename_suffix = "all"
        else:
            all_leads = lead_repo.db.query(Lead).all()
            filename_suffix = "all"
        
        if not all_leads:
            await message.answer("📭 Нет данных для экспорта")
            return
        
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
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Лиды', index=False)
        
        output.seek(0)
        excel_data = output.getvalue()
        filename = f"leads_export_{filename_suffix}_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        
        await message.answer_document(
            document=BufferedInputFile(excel_data, filename=filename),
            caption=f"📊 Экспорт лидов ({filename_suffix}) - {len(all_leads)} записей"
        )
    finally:
        lead_repo.db.close()

@admin_router.message(Command("export_clicks"))
async def admin_export_clicks(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    click_repo = get_link_click_repository()
    lead_repo = get_lead_repository()
    user_repo = get_user_repository()
    
    try:
        args = command.args
        filter_text = ""

        if args:
            if args.startswith("utm_"):
                clicks = click_repo.db.query(LinkClick).filter(
                    LinkClick.utm_source == args
                ).order_by(LinkClick.clicked_at.desc()).all()
                filter_text = f"_utm_{args}"
            elif args == "today":
                today = datetime.utcnow().date()
                clicks = click_repo.db.query(LinkClick).filter(
                    LinkClick.clicked_at >= today
                ).order_by(LinkClick.clicked_at.desc()).all()
                filter_text = "_today"
            elif args == "all":
                clicks = click_repo.db.query(LinkClick).order_by(LinkClick.clicked_at.desc()).all()
                filter_text = "_all"
            else:
                await message.answer(
                    "❌ Неизвестный фильтр\n"
                    "Доступные фильтры:\n"
                    "• utm_xxx - по UTM метке\n"
                    "• today - только сегодня\n"
                    "• all - все клики (по умолчанию)\n\n"
                    "Пример: /export_clicks utm_invest"
                )
                return
        else:
            clicks = click_repo.db.query(LinkClick).order_by(LinkClick.clicked_at.desc()).all()
            filter_text = "_all"

        if not clicks:
            await message.answer("📭 Нет данных для экспорта")
            return

        data = []
        for click in clicks:
            row = {
                'ID клика': click.id,
                'Дата и время': click.clicked_at.strftime('%Y-%m-%d %H:%M:%S'),
                'UTM источник': click.utm_source,
                'User ID': click.user_id if click.user_id else "Аноним",
            }

            if click.user_data:
                user_data = click.user_data
                row['Username'] = f"@{user_data.get('username')}" if user_data.get('username') else ""
                row['Имя'] = user_data.get('first_name', '')
                row['Фамилия'] = user_data.get('last_name', '')
            else:
                row['Username'] = ""
                row['Имя'] = ""
                row['Фамилия'] = ""

            lead = None
            if click.user_id:
                lead = lead_repo.db.query(Lead).filter(Lead.user_id == click.user_id).first()

            has_contact = False
            phone = ""
            if click.user_id:
                bot_user = user_repo.get_user_by_id(click.user_id)
                if bot_user and bot_user.has_contact:
                    has_contact = True
                    phone = bot_user.phone or ""
            
            row['Есть контакт'] = "Да" if has_contact else "Нет"
            row['Телефон'] = phone if phone else ""

            if lead:
                row['Стал лидом'] = "Да"
                row['ID лида'] = lead.id
                row['Сегмент лида'] = lead.segment
                row['Бюджет'] = lead.budget or ""
                row['Срок'] = lead.timeline or ""
                row['Статус лида'] = lead.status
                row['Дата создания лида'] = lead.created_at.strftime('%Y-%m-%d %H:%M:%S')
            else:
                row['Стал лидом'] = "Нет"
                row['ID лида'] = ""
                row['Сегмент лида'] = ""
                row['Бюджет'] = ""
                row['Срок'] = ""
                row['Статус лида'] = ""
                row['Дата создания лида'] = ""
            
            data.append(row)

        df = pd.DataFrame(data)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Клики', index=False)

            stats_data = []

            total_clicks = len(clicks)
            with_contact = df[df['Есть контакт'] == 'Да'].shape[0]
            with_lead = df[df['Стал лидом'] == 'Да'].shape[0]
            
            stats_data.append({
                'Показатель': 'Всего переходов',
                'Значение': total_clicks
            })
            stats_data.append({
                'Показатель': 'С контактом',
                'Значение': with_contact,
                'Конверсия (%)': (with_contact / total_clicks * 100) if total_clicks > 0 else 0
            })
            stats_data.append({
                'Показатель': 'Стали лидами',
                'Значение': with_lead,
                'Конверсия (%)': (with_lead / total_clicks * 100) if total_clicks > 0 else 0
            })

            utm_stats = df['UTM источник'].value_counts()
            for utm, count in utm_stats.items():
                utm_leads = df[(df['UTM источник'] == utm) & (df['Стал лидом'] == 'Да')].shape[0]
                utm_contact = df[(df['UTM источник'] == utm) & (df['Есть контакт'] == 'Да')].shape[0]
                
                stats_data.append({
                    'Показатель': f'UTM: {utm}',
                    'Значение': count
                })
                stats_data.append({
                    'Показатель': f'  → Контакты ({utm})',
                    'Значение': utm_contact,
                    'Конверсия (%)': (utm_contact / count * 100) if count > 0 else 0
                })
                stats_data.append({
                    'Показатель': f'  → Лиды ({utm})',
                    'Значение': utm_leads,
                    'Конверсия (%)': (utm_leads / count * 100) if count > 0 else 0
                })
            
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='Статистика', index=False)
        
        output.seek(0)
        excel_data = output.getvalue()
        filename = f"clicks_export{filter_text}_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        
        await message.answer_document(
            document=BufferedInputFile(excel_data, filename=filename),
            caption=f"📊 Экспорт кликов ({len(clicks)} записей)\n\n"
                   f"Фильтр: {args if args else 'все клики'}"
        )
        
    except Exception as e:
        import logging
        logging.error(f"❌ Ошибка экспорта кликов: {e}")
        await message.answer(f"❌ Ошибка при экспорте: {str(e)}")
    finally:
        click_repo.db.close()
        lead_repo.db.close()
        user_repo.db.close()

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
        "⏰ Когда отправить рассылки?\n\n"
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
    if not message.text:
        await message.answer("❌ Пожалуйста, укажите время:")
        return
        
    time_input = message.text.strip().lower()
    data = await state.get_data()
    
    try:
        send_time = parse_time_input(time_input)
        moscow_time = send_time + timedelta(hours=3)
        
        if send_time <= datetime.utcnow():
            success, failed = await send_broadcast(message.bot, data['text'], data.get('photo'))
            status = f"✅ Отправлено сразу\nУспешно: {success}, Не удалось: {failed}"
        else:
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
    now_moscow = now_utc + timedelta(hours=3)
    
    if time_input == 'now':
        return now_utc
    relative_match = re.match(r'\+(\d+)\s*(hour|hours|minute|minutes|hr|min)', time_input)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        
        if unit in ['hour', 'hours', 'hr']:
            return now_utc + timedelta(hours=amount)
        elif unit in ['minute', 'minutes', 'min']:
            return now_utc + timedelta(minutes=amount)

    if time_input.startswith('tomorrow'):
        time_part = time_input.replace('tomorrow', '').strip()
        if not time_part:
            time_part = '10:00'
        time_obj = datetime.strptime(time_part, '%H:%M').time()
        result_moscow = datetime.combine(now_moscow.date() + timedelta(days=1), time_obj)
        result_utc = result_moscow - timedelta(hours=3)
        return result_utc

    formats = [
        '%d.%m.%Y %H:%M',
        '%Y-%m-%d %H:%M',
        '%H:%M',
        '%d.%m %H:%M',
    ]
    
    for fmt in formats:
        try:
            if fmt == '%H:%M':
                time_obj = datetime.strptime(time_input, fmt).time()
                result_moscow = datetime.combine(now_moscow.date(), time_obj)
                
                if result_moscow < now_moscow:
                    result_moscow += timedelta(days=1)
                
                result_utc = result_moscow - timedelta(hours=3)
                return result_utc
            else:
                naive_dt = datetime.strptime(time_input, fmt)
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
                await asyncio.sleep(0.05)
            except Exception as e:
                print(f"❌ Ошибка отправки пользователю {user_id}: {e}")
                failed += 1
        
        return success, failed
    finally:
        lead_repo.db.close()

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

@admin_router.message(Command("quick_send"))
async def admin_quick_send(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

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

    success, failed = await send_broadcast(message.bot, text)
    
    await message.answer(
        f"📢 **БЫСТРАЯ РАССЫЛКА ОТПРАВЛЕНА**\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}\n"
        f"📝 Текст: {text[:100]}..."
    )

@admin_router.message(Command("users"))
async def admin_users(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    user_repo = get_user_repository()
    
    try:
        args = command.args
        if args:
            if args.startswith("utm_"):
                users = user_repo.get_users_by_utm(args)
                filter_text = f" (UTM: {args})"
            elif args == "no_contact":
                all_users = user_repo.get_users_by_utm()
                users = [u for u in all_users if not u['has_contact']]
                filter_text = " (без контакта)"
            elif args == "no_lead":
                all_users = user_repo.get_users_by_utm()
                users = [u for u in all_users if not u['has_lead']]
                filter_text = " (без лида)"
            elif args == "active":
                all_users = user_repo.get_users_by_utm()
                today = datetime.utcnow().date()
                users = [u for u in all_users if u['last_activity'].date() == today]
                filter_text = " (активные сегодня)"
            else:
                await message.answer(
                    "❌ Неизвестный фильтр\n"
                    "Доступные фильтры:\n"
                    "• utm_xxx - по UTM метке\n"
                    "• no_contact - без контакта\n"
                    "• no_lead - без лида\n"
                    "• active - активные сегодня"
                )
                return
        else:
            users = user_repo.get_users_by_utm()[:20]
            filter_text = ""

        if not users:
            await message.answer(f"📭 Нет пользователей{filter_text}")
            return

        users_text = f"👥 **ПОЛЬЗОВАТЕЛИ{filter_text}**\n\n"
        
        for i, user in enumerate(users, 1):
            status_emoji = {
                "visitor": "👀",
                "contact_only": "📞",
                "lead_new": "🎯",
                "lead_contacted": "💬",
                "lead_converted": "✅",
                "lead_rejected": "❌",
                "lead": "🎯"
            }.get(user['user_status'], "❓")
            
            username_display = f"@{user['username']}" if user['username'] else "без username"
            phone_display = user['phone'] if user['phone'] else "📵 нет контакта"
            
            users_text += (
                f"{status_emoji} **{user['first_name']} {user['last_name'] or ''}**\n"
                f"🔗 {username_display}\n"
                f"📞 {phone_display}\n"
                f"🏷️ UTM: {user['utm_source']}\n"
                f"📊 Статус: {user['user_status']}\n"
            )
            
            if user['lead_info'] and user['lead_info']['exists']:
                users_text += f"💰 Бюджет: {user['lead_info']['budget'] or 'не указан'}\n"
                users_text += f"⏰ Создан: {user['lead_info']['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
            
            users_text += f"🕐 Активность: {user['last_activity'].strftime('%d.%m.%Y %H:%M')}\n"
            users_text += f"---\n"

        users_text += f"\n📊 Всего: {len(users)} пользователей"
        
        await message.answer(users_text)
    finally:
        user_repo.db.close()

@admin_router.message(Command("user_stats"))
async def admin_user_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    user_repo = get_user_repository()
    lead_repo = get_lead_repository()
    
    try:
        user_stats = user_repo.get_user_stats()

        utm_stats = user_repo.get_utm_stats_detailed()

        today_leads = lead_repo.get_today_leads()
        
        stats_text = (
            "📊 **ПОЛНАЯ СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ**\n\n"
            f"👥 Всего пользователей: **{user_stats['total_users']}**\n"
            f"📞 С контактом: **{user_stats['users_with_contact']}** ({user_stats['conversion_to_contact']:.1f}%)\n"
            f"🎯 С лидами: **{user_stats['users_with_lead']}** ({user_stats['conversion_to_lead']:.1f}%)\n"
            f"🔥 Активных сегодня: **{user_stats['active_today']}**\n\n"
            f"📅 Лидов сегодня: **{len(today_leads)}**\n\n"
            "**СТАТИСТИКА ПО UTM:**\n"
        )

        sorted_utm = sorted(utm_stats.items(), key=lambda x: x[1]['total_users'], reverse=True)[:5]
        
        for utm, stats in sorted_utm:
            utm_name = config.UTM_SEGMENTS.get(utm, utm)
            stats_text += (
                f"• **{utm_name}**\n"
                f"  👥 Пользователей: {stats['total_users']}\n"
                f"  📞 Контактов: {stats['with_contact']} ({stats['contact_rate']:.1f}%)\n"
                f"  🎯 Лидов: {stats['with_lead']} ({stats['lead_rate']:.1f}%)\n"
            )

        stats_text += "\n**КОНВЕРСИОННАЯ ВОРОНКА:**\n"
        stats_text += f"👥 Все пользователи: 100%\n"
        stats_text += f"📞 Дали контакт: {user_stats['conversion_to_contact']:.1f}%\n"
        stats_text += f"🎯 Стали лидами: {user_stats['conversion_to_lead']:.1f}%\n"
        
        await message.answer(stats_text)
    finally:
        user_repo.db.close()
        lead_repo.db.close()

@admin_router.message(Command("clicks"))
async def admin_clicks(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return

    click_repo = get_link_click_repository()
    lead_repo = get_lead_repository()
    user_repo = get_user_repository()
    
    try:
        args = command.args
        filter_text = ""

        if args:
            if args.startswith("utm_"):
                clicks = click_repo.db.query(LinkClick).filter(
                    LinkClick.utm_source == args
                ).order_by(LinkClick.clicked_at.desc()).limit(50).all()
                filter_text = f" (UTM: {args})"
            elif args == "today":
                today = datetime.utcnow().date()
                clicks = click_repo.db.query(LinkClick).filter(
                    LinkClick.clicked_at >= today
                ).order_by(LinkClick.clicked_at.desc()).limit(50).all()
                filter_text = " (сегодня)"
            elif args == "no_lead":
                all_clicks = click_repo.db.query(LinkClick).order_by(LinkClick.clicked_at.desc()).limit(100).all()
                clicks_without_leads = []
                for click in all_clicks:
                    if click.user_id:
                        lead = lead_repo.db.query(Lead).filter(Lead.user_id == click.user_id).first()
                        if not lead:
                            clicks_without_leads.append(click)
                    else:
                        clicks_without_leads.append(click)
                    
                    if len(clicks_without_leads) >= 50:
                        break
                clicks = clicks_without_leads
                filter_text = " (без лида)"
            else:
                await message.answer(
                    "❌ Неизвестный фильтр\n"
                    "Доступные фильтры:\n"
                    "• utm_xxx - по UTM метке\n"
                    "• today - только сегодня\n"
                    "• no_lead - без лидов"
                )
                return
        else:
            clicks = click_repo.db.query(LinkClick).order_by(LinkClick.clicked_at.desc()).limit(50).all()

        if not clicks:
            await message.answer(f"📭 Нет кликов{filter_text}")
            return

        clicks_text = f"🖱️ **ТАБЛИЦА ПЕРЕХОДОВ{filter_text}**\n\n"
        
        total_clicks = len(clicks)
        with_leads = 0
        with_contact = 0
        
        for click in clicks:
            time_str = click.clicked_at.strftime('%H:%M')

            utm_display = click.utm_source

            user_info = ""
            contact_info = "❌"
            lead_info = "❌"
            
            if click.user_id:
                lead = lead_repo.db.query(Lead).filter(Lead.user_id == click.user_id).first()

                if click.user_data:
                    user_data = click.user_data
                    username = user_data.get('username', '')
                    first_name = user_data.get('first_name', '')
                    
                    if username:
                        user_info = f"@{username}"
                    elif first_name:
                        user_info = first_name
                    else:
                        user_info = f"ID:{click.user_id}"
                else:
                    user_info = f"ID:{click.user_id}"

                if lead:
                    with_leads += 1
                    if lead.phone:
                        contact_info = "✅"
                        with_contact += 1
                    else:
                        contact_info = "❌"
                    
                    lead_info = f"✅ ({lead.segment[:3]})"
                else:
                    bot_user = user_repo.get_user_by_id(click.user_id)
                    if bot_user and bot_user.has_contact:
                        contact_info = "✅"
                        with_contact += 1
            else:
                user_info = "Аноним"
            
            clicks_text += f"🕐 **{time_str}** | `{utm_display}`\n"
            clicks_text += f"   👤 {user_info} | 📞 {contact_info} | 🎯 {lead_info}\n"
            clicks_text += f"   ---\n"

        conversion_to_contact = (with_contact / total_clicks * 100) if total_clicks > 0 else 0
        conversion_to_lead = (with_leads / total_clicks * 100) if total_clicks > 0 else 0
        
        clicks_text += f"\n📊 **СТАТИСТИКА:**\n"
        clicks_text += f"• Всего переходов: {total_clicks}\n"
        clicks_text += f"• С контактом: {with_contact} ({conversion_to_contact:.1f}%)\n"
        clicks_text += f"• Стали лидами: {with_leads} ({conversion_to_lead:.1f}%)\n"

        if len(clicks_text) > 4000:
            parts = [clicks_text[i:i+4000] for i in range(0, len(clicks_text), 4000)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(clicks_text)
            
    except Exception as e:
        import logging
        logging.error(f"❌ Ошибка в команде /clicks: {e}")
        await message.answer(f"❌ Ошибка при получении кликов: {str(e)}")
    finally:
        click_repo.db.close()
        lead_repo.db.close()
        user_repo.db.close()

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
        "• /user_stats - полная статистика пользователей\n"
        "• /myid - узнать свой Telegram ID\n\n"
        
        "👥 **Пользователи:**\n"
        "• /users - все пользователи\n"
        "• /users utm_invest - по UTM\n"
        "• /users no_contact - без контакта\n"
        "• /users no_lead - без лида\n"
        "• /users active - активные сегодня\n\n"
        
        "🎯 **Лиды:**\n"
        "• /leads - просмотр лидов за сегодня\n"
        "• /leads [сегмент] - лиды по сегменту\n\n"
        
        "🖱️ **Переходы (клики):**\n"
        "• /clicks - таблица всех переходов\n"
        "• /clicks utm_xxx - переходы по UTM\n"
        "• /clicks today - переходы за сегодня\n"
        "• /clicks no_lead - переходы без лидов\n\n"
        
        "🔗 **Ссылки:**\n"  
        "• /links - генератор UTM ссылок с статистикой\n\n"
        
        "📁 **Экспорт:**\n"
        "• /export - экспорт всех лидов в Excel\n"
        "• /export today - экспорт только сегодняшних лидов\n"
        "• /export all - экспорт всех лидов (по умолчанию)\n"
        "• /export_clicks - экспорт всех кликов в Excel\n"
        "• /export_clicks utm_xxx - экспорт кликов по UTM\n"
        "• /export_clicks today - экспорт сегодняшних кликов\n"
        "• /export_clicks all - экспорт всех кликов\n\n"
        
        "📢 **Рассылки:**\n"
        "• /broadcast - создание рассылки (текст + фото + время)\n"
        "• /broadcasts - просмотр запланированных рассылок\n"
        "• /quick_send [текст] - быстрая рассылка (только текст)\n"
        "• /check_broadcasts - проверить и отправить запланированные\n\n"
        
        "💬 **Переписка с пользователями:**\n"
        "• /unread - непрочитанные сообщения\n"
        "• /toggle_chat - включить/выключить переписку\n\n"
        
        "💡 **Примеры:**\n"
        "• /leads investment\n"
        "• /utm_stats utm_invest\n"
        "• /clicks today\n"
        "• /users utm_realestate\n"
        "• /quick_send Привет! У нас новые предложения\n"
        "• /export today\n\n"
        "⏰ *Время в рассылках указывается по Москве*"
    )
    
    await message.answer(help_text)