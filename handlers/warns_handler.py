import re
from datetime import datetime
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, update
# Импортируем desc для сортировки (чтобы снимать последнее наказание)
from sqlalchemy import desc
from db import AsyncSessionLocal
from models import Warn, RoleAssignment, Nick
from utils import parse_duration, format_timedelta_remaining
from keyboards import page_kb
from config import cfg

router = Router()


async def format_user_link(chat_id: int, user_id: int, bot, session):
    q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == user_id))
    nick = q.scalars().first()
    if nick:
        display = nick.nick
    else:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            display = member.user.full_name
        except Exception:
            display = str(user_id)
    return f'<a href="tg://user?id={user_id}">{display}</a>'


# --- ХЕНДЛЕР ВЫДАЧИ ПРЕДУПРЕЖДЕНИЯ ---
@router.message(
    lambda message: message.text and re.match(r"^(варн|\+варн|\+пред|пред)\b", message.text.strip(), re.IGNORECASE))
async def cmd_warn(message: Message):
    parts = message.text.strip().split(maxsplit=2)

    # 1. ПРОВЕРКА: Если написали просто "пред" или "+пред" без аргументов и без реплая
    # Выводим красивую справку
    if len(parts) < 2 and not message.reply_to_message:
        help_text = (
            "<b>ℹ️ Справка по команде:</b>\n\n"
            "Используйте: <code>+пред</code> [время] [причина]\n"
            "Или ответом на сообщение: <code>+пред</code> [время]\n\n"
            "<i>Примеры:</i>\n"
            "• <code>+пред 10м Спам</code>\n"
            "• <code>+пред 1ч Оскорбление</code>\n"
            "• <code>+пред 1д</code> (без причины)"
        )
        await message.reply(help_text, parse_mode="HTML")
        return

    # Who issues?
    issuer = message.from_user.id
    chat_id = message.chat.id

    # Check issuer role
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
    if not caller_assign or caller_assign.role_id < 1:
        await message.reply("Вы не имеете права выдавать предупреждения.", parse_mode=cfg.PARSE_MODE)
        return

    # target detection
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        token = parts[1]
        if token.startswith("@"):
            await message.reply(
                "Пожалуйста, используйте reply на сообщение пользователя или укажите его id (не @username).",
                parse_mode=cfg.PARSE_MODE)
            return
        if token.isdigit():
            target_id = int(token)
        else:
            await message.reply("Не удалось определить пользователя.", parse_mode=cfg.PARSE_MODE)
            return

    # parse time and reason
    time_td = None
    reason = None

    # Логика разбора аргументов
    if message.reply_to_message:
        if len(parts) >= 2:
            maybe_time = parts[1]
            td = parse_duration(maybe_time)
            if td:
                time_td = td
                if len(parts) == 3:
                    reason = parts[2]
            else:
                reason = " ".join(parts[1:])
    else:
        if len(parts) >= 3:
            td = parse_duration(parts[1])
            if td:
                time_td = td
                reason = parts[2]
            else:
                reason = parts[2]
        elif len(parts) == 2:
            td = parse_duration(parts[1])
            if td:
                time_td = td
            else:
                reason = parts[1]

    until_dt = None
    if time_td:
        # Используем .now() для корректного локального времени
        until_dt = datetime.now() + time_td

    async with AsyncSessionLocal() as session:
        w = Warn(chat_id=chat_id, user_id=target_id, issued_by=issuer, reason=reason, until=until_dt, active=True)
        session.add(w)
        await session.commit()
        await session.refresh(w)
        link = await format_user_link(chat_id, target_id, message.bot, session)

    until_text = until_dt.strftime("%H:%M:%S %d.%m.%Y") if until_dt else "без срока"
    await message.reply(f"⚠️ {link} получил предупреждение до {until_text} за: {reason or 'Причина не указана'}.",
                        parse_mode=cfg.PARSE_MODE)


# --- ХЕНДЛЕР СНЯТИЯ ПРЕДУПРЕЖДЕНИЯ ---
@router.message(
    lambda message: message.text and re.match(r"^(-варн|-пред|снять)\b", message.text.strip(), re.IGNORECASE))
async def cmd_unwarn(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    chat_id = message.chat.id
    target_id = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        if len(parts) >= 2:
            token = parts[1].split()[0]
            if token.isdigit():
                target_id = int(token)

    if not target_id:
        await message.reply("Ответьте на сообщение пользователя или укажите его id.", parse_mode=cfg.PARSE_MODE)
        return

    issuer = message.from_user.id

    async with AsyncSessionLocal() as session:
        # Проверка прав
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
        if not caller_assign or caller_assign.role_id < 1:
            await message.reply("Вы не имеете права снимать предупреждения.", parse_mode=cfg.PARSE_MODE)
            return

        # !!! ИСПРАВЛЕНИЕ ЛОГИКИ СНЯТИЯ !!!
        # Мы ищем только ПОСЛЕДНЕЕ активное предупреждение
        stmt = select(Warn).where(
            Warn.chat_id == chat_id,
            Warn.user_id == target_id,
            Warn.active == True
        ).order_by(desc(Warn.created_at)).limit(1)

        result = await session.execute(stmt)
        warn_to_remove = result.scalars().first()

        link = await format_user_link(chat_id, target_id, message.bot, session)

        if warn_to_remove:
            warn_to_remove.active = False
            await session.commit()
            await message.reply(f"✅ С {link} было снято 1 предупреждение.", parse_mode=cfg.PARSE_MODE)
        else:
            await message.reply(f"У пользователя {link} нет активных предупреждений.", parse_mode=cfg.PARSE_MODE)


# --- ХЕНДЛЕР СПИСКА ПРЕДУПРЕЖДЕНИЙ ---
@router.message(
    lambda message: message.text and re.match(r"^(\?пред|\?варн)(\s+(\d+))?$", message.text.strip(), re.IGNORECASE))
async def cmd_list_warns(message: Message):
    chat_id = message.chat.id
    text = message.text.strip()
    parts = text.split()
    page = 1
    if len(parts) >= 2 and parts[1].isdigit():
        page = max(1, int(parts[1]))
    per_page = 10
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
        warns = q.scalars().all()
    total = len(warns)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    page_warns = warns[start:start + per_page]

    text_lines = []
    text_lines.append("⚠️ Активные предупреждения в чате")
    text_lines.append(f"┌─ Всего активных предупреждений: {total}")
    text_lines.append("├─ Список предупреждений:")

    async with AsyncSessionLocal() as session:
        for idx, w in enumerate(page_warns, start=start + 1):
            rem = format_timedelta_remaining(w.until) if w.until else "без срока"
            link = await format_user_link(chat_id, w.user_id, message.bot, session)
            text_lines.append(f"│   {idx}. {link} наказан за {w.reason or 'Причина не указана'} до ({rem})")

    text_lines.append(f"└─ Страница: {page}/{total_pages}")
    kb = page_kb(page, prefix="warns")
    await message.reply("\n".join(text_lines), reply_markup=kb, parse_mode=cfg.PARSE_MODE)


@router.callback_query(lambda c: c.data and c.data.startswith("warns:"))
async def cb_warns_page(query: CallbackQuery):
    parts = query.data.split(":")
    try:
        page = int(parts[1])
    except Exception:
        page = 1
    if page < 1:
        page = 1
    per_page = 10
    chat_id = query.message.chat.id
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
        warns = q.scalars().all()
    total = len(warns)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    page_warns = warns[start:start + per_page]

    text_lines = []
    text_lines.append("⚠️ Активные предупреждения в чате")
    text_lines.append(f"┌─ Всего активных предупреждений: {total}")
    text_lines.append("├─ Список предупреждений:")
    async with AsyncSessionLocal() as session:
        for idx, w in enumerate(page_warns, start=start + 1):
            rem = format_timedelta_remaining(w.until) if w.until else "без срока"
            link = await format_user_link(chat_id, w.user_id, query.bot, session)
            text_lines.append(f"│   {idx}. {link} наказан за {w.reason or 'Причина не указана'} до ({rem})")
    text_lines.append(f"└─ Страница: {page}/{total_pages}")
    kb = page_kb(page, prefix="warns")
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode=cfg.PARSE_MODE)
    except Exception:
        await query.answer("Не удалось обновить сообщение.", show_alert=False)
        return
    await query.answer()