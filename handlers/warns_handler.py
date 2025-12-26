import re
from datetime import datetime
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, update
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


@router.message(lambda message: message.text and re.match(r"^(варн|\+варн|\+пред|пред)\b", message.text.strip(), re.IGNORECASE))
async def cmd_warn(message: Message):
    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 2 and not message.reply_to_message:
        await message.reply("Использование: варн [@user или reply] [время (например 10m, 1h)] [причина опционально]", parse_mode=cfg.PARSE_MODE)
        return
    # Who issues?
    issuer = message.from_user.id
    chat_id = message.chat.id

    # Check issuer role: only users with role_id >= 1 (Мл. модератор и выше) can warn
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
    if not caller_assign or caller_assign.role_id < 1:
        await message.reply("Вы не имеете права выдавать предупреждения.", parse_mode=cfg.PARSE_MODE)
        return

    # target
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        token = parts[1]
        if token.startswith("@"):
            await message.reply("Пожалуйста, используйте reply на сообщение пользователя или укажите его id (не @username).", parse_mode=cfg.PARSE_MODE)
            return
        if token.isdigit():
            target_id = int(token)
        else:
            await message.reply("Не удалось определить пользователя.", parse_mode=cfg.PARSE_MODE)
            return

    # parse time and reason
    time_td = None
    reason = None
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
        until_dt = datetime.utcnow() + time_td

    async with AsyncSessionLocal() as session:
        w = Warn(chat_id=chat_id, user_id=target_id, issued_by=issuer, reason=reason, until=until_dt, active=True)
        session.add(w)
        await session.commit()
        await session.refresh(w)
        link = await format_user_link(chat_id, target_id, message.bot, session)

    until_text = until_dt.strftime("%H:%M:%S %d.%m.%Y") if until_dt else "без срока"
    await message.reply(f"⚠️ {link} получил предупреждение до {until_text} за: {reason or 'Причина не указана'}.", parse_mode=cfg.PARSE_MODE)


@router.message(lambda message: message.text and re.match(r"^(-варн|-пред|снять)\b", message.text.strip(), re.IGNORECASE))
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
    # permission check: only moderator+ can remove
    issuer = message.from_user.id
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
        if not caller_assign or caller_assign.role_id < 1:
            await message.reply("Вы не имеете права снимать предупреждения.", parse_mode=cfg.PARSE_MODE)
            return
        await session.execute(update(Warn).where(Warn.chat_id == chat_id, Warn.user_id == target_id, Warn.active == True).values(active=False))
        await session.commit()
        link = await format_user_link(chat_id, target_id, message.bot, session)
    await message.reply(f"✅ С {link} было снято предупреждение.", parse_mode=cfg.PARSE_MODE)


@router.message(lambda message: message.text and re.match(r"^(\?пред|\?варн)(\s+(\d+))?$", message.text.strip(), re.IGNORECASE))
async def cmd_list_warns(message: Message):
    """
    ?пред or ?варн optionally with page number: '?пред 2'
    """
    chat_id = message.chat.id
    text = message.text.strip()
    parts = text.split()
    page = 1
    if len(parts) >= 2 and parts[1].isdigit():
        page = max(1, int(parts[1]))
    per_page = 10
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
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
    # we need to fetch links - open a session for that
    async with AsyncSessionLocal() as session:
        for idx, w in enumerate(page_warns, start=start + 1):
            rem = format_timedelta_remaining(w.until) if w.until else "без срока"
            link = await format_user_link(chat_id, w.user_id, message.bot, session)
            text_lines.append(f"│   {idx}. {link} наказан за {w.reason or 'Причина не указана'} до ({rem})")
    text_lines.append(f"└─ Страница: {page}/{total_pages}")
    kb = page_kb(page, prefix="warns")
    # send initial message with inline keyboard; subsequent presses will edit this message
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
        q = await session.execute(select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
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
    # Edit the original message (do not send a new one)
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode=cfg.PARSE_MODE)
    except Exception as e:
        # if editing fails, just answer the callback (do not create new message)
        await query.answer("Не удалось обновить сообщение.", show_alert=False)
        return
    await query.answer()