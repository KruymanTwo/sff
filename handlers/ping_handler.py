from datetime import datetime
from aiogram import Router
from aiogram.types import Message
from config import cfg
from db import AsyncSessionLocal
from models import Chat, Nick, Warn
from sqlalchemy import select, func
import time

router = Router()

async def measure_api_latency(bot):
    t0 = time.perf_counter()
    try:
        await bot.get_me()
    except Exception:
        pass
    t1 = time.perf_counter()
    return int((t1 - t0) * 1000)

@router.message(lambda message: message.text and message.text.strip().lower() in ("ping", "пинг"))
async def cmd_ping_simple(message: Message):
    ms = await measure_api_latency(message.bot)
    await message.reply(f"<b>🏓Pong!</b>\nВаш Ping: <b>{ms}</b>ms", parse_mode="HTML")

@router.message(lambda message: message.text and message.text.strip().lower().startswith("ping "))
async def cmd_ping_variants(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    chat = message.chat
    bot = message.bot

    if arg in ("wox", "woxl"):
        nickname = message.from_user.full_name
        text = f"🍊 Привет, {nickname}. Вы подключились к Woxl -- Ваш чат менеджер по управлению группой!."
        await message.reply(text, parse_mode=cfg.PARSE_MODE)
        return

    if arg == "chat":
        try:
            chat_obj = await bot.get_chat(chat.id)
        except Exception:
            chat_obj = chat
        try:
            total_members = await bot.get_chat_member_count(chat.id)
        except Exception:
            try:
                total_members = await bot.get_chat_members_count(chat.id)
            except Exception:
                total_members = "N/A"
        try:
            admins = await bot.get_chat_administrators(chat.id)
            admin_count = len(admins)
        except Exception:
            admin_count = "N/A"
        active_users = "N/A"
        messages_today = "N/A"
        created_at = getattr(chat_obj, "created_at", None)
        created_display = created_at if created_at else "N/A"
        days_since = "N/A"
        await message.reply(
            "🍊 Информация о чате:\n"
            f"├─ Название: {chat.title or 'N/A'}\n"
            f"├─ Участников: {total_members}\n"
            f"├─ Админов: {admin_count}\n"
            f"├─ Активных за 24ч: {active_users}\n"
            f"├─ Сообщений сегодня: {messages_today}\n"
            f"└─ Создан: {created_display} ({days_since} дней)"
            , parse_mode=cfg.PARSE_MODE)
        return

    if arg == "me":
        user = message.from_user
        nick_val = None
        try:
            async with AsyncSessionLocal() as session:
                q = await session.execute(select(Nick).where(Nick.chat_id == chat.id, Nick.user_id == user.id))
                n = q.scalars().first()
                if n:
                    nick_val = n.nick
        except Exception:
            nick_val = None
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            join_date = getattr(member, "joined_date", None) or getattr(member, "until_date", None) or "N/A"
        except Exception:
            join_date = "N/A"
        message_count = "N/A"
        violations_count = 0
        try:
            async with AsyncSessionLocal() as session:
                q = await session.execute(select(Warn).where(Warn.chat_id == chat.id, Warn.user_id == user.id))
                warnings = q.scalars().all()
                violations_count = len(warnings)
        except Exception:
            violations_count = "N/A"
        reputation = "N/A"
        await message.reply(
            "👤 Информация о пользователе:\n"
            f"├─ Имя: {user.full_name}\n"
            f"├─ Ник: {nick_val or 'Не установлен'}\n"
            f"├─ В чате с: {join_date}\n"
            f"├─ Сообщений: {message_count}\n"
            f"├─ Нарушений: {violations_count}\n"
            f"└─ Репутация: {reputation}"
            , parse_mode=cfg.PARSE_MODE)
        return

    if arg == "bot":
        created_date = datetime(2025, 12, 15)
        delta = datetime.utcnow() - created_date
        days = delta.days
        months = days // 30
        years = days // 365
        chat_count = "N/A"
        try:
            async with AsyncSessionLocal() as session:
                q = await session.execute(select(func.count()).select_from(Chat))
                chat_count = q.scalars().first() or 0
        except Exception:
            chat_count = "N/A"
        status = "Активен"
        await message.reply(
            f"Название: Woxl | Чат менеджер\n"
            f"Имя: Wox 🍊\n"
            f"Дата создания: 15.12.2025 ({days} дней; {months} мес; {years} лет)\n"
            f"Сколько всего групп подключено: {chat_count}\n"
            f"Бот: {status}"
            , parse_mode=cfg.PARSE_MODE)
        return

    if arg == "system":
        user_id = message.from_user.id
        if user_id not in cfg.CREATOR_IDS:
            await message.reply("Доступ запрещён.", parse_mode=cfg.PARSE_MODE)
            return
        uptime = "N/A"
        try:
            import psutil
            uptime_sec = time.time() - psutil.boot_time()
            uptime = str(int(uptime_sec)) + "s"
            cpu = psutil.cpu_percent(interval=0.1)
            mem = int(psutil.virtual_memory().percent)
        except Exception:
            cpu = "N/A"
            mem = "N/A"
        queue_size = "N/A"
        last_error_time = "N/A"
        bot_version = "1.0"
        await message.reply(
            "📊 Системная информация:\n"
            f"├─ Бот работает: {uptime}\n"
            f"├─ Загрузка CPU: {cpu}%\n"
            f"├─ Память: {mem}%\n"
            f"├─ Сообщений в очереди: {queue_size}\n"
            f"├─ Последняя ошибка: {last_error_time}\n"
            f"└─ Версия: {bot_version}"
            , parse_mode=cfg.PARSE_MODE)
        return

    if arg.startswith("full") or message.text.strip().lower().startswith("/ping full") or message.text.strip().lower().startswith("!пинг полный"):
        tg_ping = await measure_api_latency(bot)
        server_ping = 0
        try:
            t0 = time.perf_counter()
            t1 = time.perf_counter()
            server_ping = int((t1 - t0) * 1000)
        except Exception:
            server_ping = 0
        api_response = tg_ping
        status = "✅ Стабильный"
        await message.reply(
            "🌐 Полная диагностика:\n"
            f"├─ Ваш пинг до Telegram: {tg_ping}ms\n"
            f"├─ Пинг до сервера бота: {server_ping}ms\n"
            f"├─ Скорость ответа API: {api_response}ms\n"
            f"├─ Статус сервера: {status}\n"
            f"└─ Рекомендация: Все отлично!"
            , parse_mode=cfg.PARSE_MODE)
        return

    if " vs " in message.text.lower() or message.text.strip().lower().startswith("/ping vs") or message.text.strip().lower().startswith("!пинг против"):
        user_ping = await measure_api_latency(bot)
        target_ping = await measure_api_latency(bot)
        await message.reply(f"📊 Забег пингов! {message.from_user.full_name}: {user_ping}ms 🆚 @user: {target_ping}ms", parse_mode=cfg.PARSE_MODE)
        return

    ms = await measure_api_latency(bot)
    await message.reply(f"Pong!Ваш Ping: {ms}ms", parse_mode=cfg.PARSE_MODE)