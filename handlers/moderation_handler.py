# handlers/moderation_handler.py
from datetime import datetime
from aiogram import Router
from aiogram.types import Message, CallbackQuery, ChatPermissions
from sqlalchemy import select, desc
from db import AsyncSessionLocal
from models import Mute, Ban, RoleAssignment, Nick
from utils import parse_duration, format_timedelta_remaining
from keyboards import page_kb
from config import cfg
import re

router = Router()

# ----------------- helpers -----------------

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

async def resolve_target_from_message(message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name
    parts = message.text.strip().split()
    if len(parts) < 2:
        return None, None
    token = parts[1].split()[0]
    if token.isdigit():
        return int(token), token
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and getattr(ent, "user", None):
                return ent.user.id, ent.user.full_name
    if token.startswith("@"):
        return token, token
    return None, None

async def get_effective_role(chat_id: int, user_id_or_token, bot):
    if isinstance(user_id_or_token, int):
        async with AsyncSessionLocal() as session:
            q = await session.execute(select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == user_id_or_token))
            ra = q.scalars().first()
            if ra:
                return ra.role_id
    # try to resolve via telegram (if we have numeric id)
    try:
        if isinstance(user_id_or_token, int):
            member = await bot.get_chat_member(chat_id, user_id_or_token)
            status = getattr(member, "status", "").lower()
            if status == "creator":
                return 5
            if status == "administrator":
                return 4
            return 0
    except Exception:
        pass
    return None

async def try_resolve_username_to_id(chat_id: int, username_token: str, bot):
    name = username_token.lstrip("@")
    try:
        # best-effort: try to get chat member by username; some Telegram API variants allow username
        member = await bot.get_chat_member(chat_id, name)
        return member.user.id, member.user.full_name
    except Exception:
        try:
            member = await bot.get_chat_member(chat_id, f"@{name}")
            return member.user.id, member.user.full_name
        except Exception:
            return None, None

async def is_user_present_in_chat(chat_id: int, user_id: int, bot):
    """
    Возвращает (present: bool, status: str | None)
    present = False если статус 'left' или 'kicked' или если произошла ошибка при получении.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = getattr(member, "status", "").lower()
        if status in ("left", "kicked"):
            return False, status
        return True, status
    except Exception:
        # Если не удалось получить — считаем, что пользователь не подтверждён (без выдачи наказаний)
        return False, None

# ----------------- list mutes -----------------

@router.message(lambda message: message.text and (
    message.text.strip().lower() in ("мутлист","муты","мут лист","mutelist","/мутлист","/mutelist","?mute","?мут")
    or message.text.strip().lower().startswith(("мутлист ","муты ","мут лист ","mutelist ","/мутлист ","/mutelist ","?mute ","?мут "))
))
async def cmd_list_mutes(message: Message):
    parts = message.text.strip().split()
    page = 1
    if len(parts) >= 2 and parts[1].isdigit():
        page = max(1, int(parts[1]))
    per_page = 10
    chat_id = message.chat.id
    target_user_id = None
    target_display = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(select(Mute).where(Mute.chat_id == chat_id, Mute.active == True, Mute.user_id == target_user_id).order_by(Mute.created_at.desc()))
            mutes = q.scalars().all()
            target_display = await format_user_link(chat_id, target_user_id, message.bot, session)
        else:
            q = await session.execute(select(Mute).where(Mute.chat_id == chat_id, Mute.active == True).order_by(Mute.created_at.desc()))
            mutes = q.scalars().all()
    total = len(mutes)
    if total == 0:
        if target_user_id:
            await message.reply(f"Информация: {target_display} не имеет активных мутов.", parse_mode="HTML")
        else:
            await message.reply("Информация: в чате нет активных мутов.", parse_mode="HTML")
        return
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_mutes = mutes[start:start + per_page]
    text_lines = []
    header = "Активные муты"
    if target_user_id:
        header = f"Активные муты для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных мутов:</b> {total}")
    text_lines.append("├─ <b>Список мутов:</b>")
    async with AsyncSessionLocal() as session:
        for idx, m in enumerate(page_mutes, start=start + 1):
            rem = format_timedelta_remaining(m.until) if m.until else "без срока"
            link = await format_user_link(chat_id, m.user_id, message.bot, session)
            issuer_link = await format_user_link(chat_id, m.issued_by, message.bot, session) if m.issued_by else "Система"
            created = m.created_at.strftime("%d.%m.%Y %H:%M") if getattr(m, "created_at", None) else ""
            text_lines.append(f"│   {idx}. {link} — <b>за</b>: {m.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}")
    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="mutes")
    await message.reply("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("mutes:"))
async def cb_mutes_page(query: CallbackQuery):
    parts = query.data.split(":")
    try:
        page = int(parts[1])
    except Exception:
        page = 1
    if page < 1:
        page = 1
    per_page = 10
    chat_id = query.message.chat.id
    target_user_id = None
    target_display = None
    if query.message.reply_to_message and query.message.reply_to_message.from_user:
        target_user_id = query.message.reply_to_message.from_user.id
    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(select(Mute).where(Mute.chat_id == chat_id, Mute.active == True, Mute.user_id == target_user_id).order_by(Mute.created_at.desc()))
            mutes = q.scalars().all()
            target_display = await format_user_link(chat_id, target_user_id, query.bot, session)
        else:
            q = await session.execute(select(Mute).where(Mute.chat_id == chat_id, Mute.active == True).order_by(Mute.created_at.desc()))
            mutes = q.scalars().all()
    total = len(mutes)
    if total == 0:
        await query.answer()
        return
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_mutes = mutes[start:start + per_page]
    text_lines = []
    header = "Активные муты"
    if target_user_id:
        header = f"Активные муты для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных мутов:</b> {total}")
    text_lines.append("├─ <b>Список мутов:</b>")
    async with AsyncSessionLocal() as session:
        for idx, m in enumerate(page_mutes, start=start + 1):
            rem = format_timedelta_remaining(m.until) if m.until else "без срока"
            link = await format_user_link(chat_id, m.user_id, query.bot, session)
            issuer_link = await format_user_link(chat_id, m.issued_by, query.bot, session) if m.issued_by else "Система"
            created = m.created_at.strftime("%d.%m.%Y %H:%M") if getattr(m, "created_at", None) else ""
            text_lines.append(f"│   {idx}. {link} — <b>за</b>: {m.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}")
    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="mutes")
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")
    except Exception:
        await query.answer("Не удалось обновить сообщение.", show_alert=False)
        return
    await query.answer()

# ----------------- mute -----------------

@router.message(lambda message: message.text and re.match(r"^(?:\+?мут|\+?замутить|mute|замутить)\b", message.text.strip(), re.IGNORECASE))
async def cmd_mute(message: Message):
    parts = message.text.strip().split(maxsplit=2)
    issuer = message.from_user.id
    chat_id = message.chat.id
    role = await get_effective_role(chat_id, issuer, message.bot)
    if role is None or role < 2:
        await message.reply("<b>Ошибка: у вас нет прав для выдачи мута.</b>", parse_mode="HTML")
        return

    target, token = await resolve_target_from_message(message)
    if isinstance(target, str) and target.startswith("@"):
        uid, name = await try_resolve_username_to_id(chat_id, target, message.bot)
        if not uid:
            await message.reply("<b>Пожалуйста, ответьте на сообщение пользователя или укажите его id (без @username).</b>", parse_mode="HTML")
            return
        target = uid

    if not target:
        await message.reply("<b>Пожалуйста, ответьте на сообщение или укажите ID пользователя.</b>", parse_mode="HTML")
        return

    # Проверка, присутствует ли пользователь в чате (не вышел и не кикнут)
    present, status = await is_user_present_in_chat(chat_id, target, message.bot)
    async with AsyncSessionLocal() as session:
        link = await format_user_link(chat_id, target, message.bot, session)
    if not present:
        await message.reply(f"<b>Невозможно выдать мут {link}: пользователь вышел или был удалён/забанен.</b>", parse_mode="HTML")
        return

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
            td = parse_duration(parts[2])
            if td:
                time_td = td
            else:
                td2 = parse_duration(parts[1])
                if td2:
                    time_td = td2
                    reason = " ".join(parts[2:])
                else:
                    reason = " ".join(parts[2:])
        elif len(parts) == 2:
            pass

    until_dt = None
    if time_td:
        until_dt = datetime.now() + time_td

    async with AsyncSessionLocal() as session:
        m = Mute(chat_id=chat_id, user_id=target, issued_by=issuer, reason=reason, until=until_dt, active=True)
        session.add(m)
        await session.commit()
        await session.refresh(m)
        try:
            perms = ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_send_documents=False
            )
            await message.bot.restrict_chat_member(chat_id, target, permissions=perms, until_date=until_dt)
        except Exception:
            pass
        link = await format_user_link(chat_id, target, message.bot, session)

    until_text = until_dt.strftime("%H:%M:%S %d.%m.%Y") if until_dt else "без срока"
    await message.reply(f"<b>{link} временно ограничен в отправке сообщений до {until_text}.</b>\nПричина: {reason or 'Причина не указана'}", parse_mode="HTML")

# ----------------- unmute -----------------

@router.message(lambda message: message.text and re.match(r"^(-мут|размутить|размут|unmute)\b", message.text.strip(), re.IGNORECASE))
async def cmd_unmute(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    chat_id = message.chat.id
    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user.id
    else:
        if len(parts) >= 2:
            token = parts[1].split()[0]
            if token.isdigit():
                target = int(token)
            elif token.startswith("@"):
                uid, _ = await try_resolve_username_to_id(chat_id, token, message.bot)
                if uid:
                    target = uid
    if not target:
        await message.reply("<b>Пожалуйста, ответьте на сообщение пользователя или укажите его id.</b>", parse_mode="HTML")
        return
    issuer = message.from_user.id
    role = await get_effective_role(chat_id, issuer, message.bot)
    if role is None or role < 2:
        await message.reply("<b>Ошибка: у вас нет прав снимать муты.</b>", parse_mode="HTML")
        return
    async with AsyncSessionLocal() as session:
        stmt = select(Mute).where(Mute.chat_id == chat_id, Mute.user_id == target, Mute.active == True).order_by(desc(Mute.created_at)).limit(1)
        result = await session.execute(stmt)
        mute_to_remove = result.scalars().first()
        link = await format_user_link(chat_id, target, message.bot, session)
        if mute_to_remove:
            mute_to_remove.active = False
            await session.commit()
            try:
                perms = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_send_documents=True
                )
                await message.bot.restrict_chat_member(chat_id, target, permissions=perms)
            except Exception:
                pass
            await message.reply(f"<b>С {link} был снят мут.</b>", parse_mode="HTML")
        else:
            await message.reply(f"Информация: у пользователя {link} нет активных мутов.", parse_mode="HTML")

# ----------------- list bans -----------------

@router.message(lambda message: message.text and (message.text.strip().lower().startswith(("список банов","бан лист","банлист","banlist","ban list","?баны")) or message.text.strip().lower() == "список банов" or message.text.strip().lower() == "?баны"))
async def cmd_list_bans(message: Message):
    parts = message.text.strip().split()
    page = 1
    if len(parts) >= 2 and parts[1].isdigit():
        page = max(1, int(parts[1]))
    per_page = 10
    chat_id = message.chat.id
    target_user_id = None
    target_display = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(select(Ban).where(Ban.chat_id == chat_id, Ban.active == True, Ban.user_id == target_user_id).order_by(Ban.created_at.desc()))
            bans = q.scalars().all()
            target_display = await format_user_link(chat_id, target_user_id, message.bot, session)
        else:
            q = await session.execute(select(Ban).where(Ban.chat_id == chat_id, Ban.active == True).order_by(Ban.created_at.desc()))
            bans = q.scalars().all()
    total = len(bans)
    if total == 0:
        if target_user_id:
            await message.reply(f"Информация: {target_display} не имеет активных банов.", parse_mode="HTML")
        else:
            await message.reply("Информация: в чате нет активных банов.", parse_mode="HTML")
        return
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_bans = bans[start:start + per_page]
    text_lines = []
    header = "Активные баны"
    if target_user_id:
        header = f"Активные баны для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных банов:</b> {total}")
    text_lines.append("├─ <b>Список банов:</b>")
    async with AsyncSessionLocal() as session:
        for idx, b in enumerate(page_bans, start=start + 1):
            rem = format_timedelta_remaining(b.until) if b.until else "без срока"
            link = await format_user_link(chat_id, b.user_id, message.bot, session)
            issuer_link = await format_user_link(chat_id, b.issued_by, message.bot, session) if b.issued_by else "Система"
            created = b.created_at.strftime("%d.%m.%Y %H:%M") if getattr(b, "created_at", None) else ""
            text_lines.append(f"│   {idx}. {link} — <b>за</b>: {b.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}")
    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="bans")
    await message.reply("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("bans:"))
async def cb_bans_page(query: CallbackQuery):
    parts = query.data.split(":")
    try:
        page = int(parts[1])
    except Exception:
        page = 1
    if page < 1:
        page = 1
    per_page = 10
    chat_id = query.message.chat.id
    target_user_id = None
    target_display = None
    if query.message.reply_to_message and query.message.reply_to_message.from_user:
        target_user_id = query.message.reply_to_message.from_user.id
    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(select(Ban).where(Ban.chat_id == chat_id, Ban.active == True, Ban.user_id == target_user_id).order_by(Ban.created_at.desc()))
            bans = q.scalars().all()
            target_display = await format_user_link(chat_id, target_user_id, query.bot, session)
        else:
            q = await session.execute(select(Ban).where(Ban.chat_id == chat_id, Ban.active == True).order_by(Ban.created_at.desc()))
            bans = q.scalars().all()
    total = len(bans)
    if total == 0:
        await query.answer()
        return
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    page_bans = bans[start:start + per_page]
    text_lines = []
    header = "Активные баны"
    if target_user_id:
        header = f"Активные баны для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных банов:</b> {total}")
    text_lines.append("├─ <b>Список банов:</b>")
    async with AsyncSessionLocal() as session:
        for idx, b in enumerate(page_bans, start=start + 1):
            rem = format_timedelta_remaining(b.until) if b.until else "без срока"
            link = await format_user_link(chat_id, b.user_id, query.bot, session)
            issuer_link = await format_user_link(chat_id, b.issued_by, query.bot, session) if b.issued_by else "Система"
            created = b.created_at.strftime("%d.%m.%Y %H:%M") if getattr(b, "created_at", None) else ""
            text_lines.append(f"│   {idx}. {link} — <b>за</b>: {b.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}")
    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="bans")
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")
    except Exception:
        await query.answer("Не удалось обновить сообщение.", show_alert=False)
        return
    await query.answer()

# ----------------- ban -----------------

@router.message(lambda message: message.text and re.match(r"^(?:\+бан|\+?ban|бан)\b", message.text.strip(), re.IGNORECASE))
async def cmd_ban(message: Message):
    parts = message.text.strip().split(maxsplit=2)
    issuer = message.from_user.id
    chat_id = message.chat.id
    role = await get_effective_role(chat_id, issuer, message.bot)
    if role is None or role < 3:
        await message.reply("<b>Ошибка: у вас нет прав для выдачи бана.</b>", parse_mode="HTML")
        return

    target, token = await resolve_target_from_message(message)
    if isinstance(target, str) and target.startswith("@"):
        uid, name = await try_resolve_username_to_id(chat_id, target, message.bot)
        if not uid:
            await message.reply("<b>Пожалуйста, ответьте на сообщение пользователя или укажите его id (без @username).</b>", parse_mode="HTML")
            return
        target = uid

    if not target:
        await message.reply("<b>Пожалуйста, ответьте на сообщение или укажите ID пользователя.</b>", parse_mode="HTML")
        return

    # Проверка, присутствует ли пользователь в чате (не вышел и не кикнут)
    present, status = await is_user_present_in_chat(chat_id, target, message.bot)
    async with AsyncSessionLocal() as session:
        link = await format_user_link(chat_id, target, message.bot, session)
    if not present:
        await message.reply(f"<b>Невозможно выдать бан {link}: пользователь вышел или уже удалён/забанен.</b>", parse_mode="HTML")
        return

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
            td = parse_duration(parts[2])
            if td:
                time_td = td
            else:
                td2 = parse_duration(parts[1])
                if td2:
                    time_td = td2
                    reason = " ".join(parts[2:])
                else:
                    reason = " ".join(parts[2:])
        elif len(parts) == 2:
            pass

    until_dt = None
    if time_td:
        until_dt = datetime.now() + time_td

    async with AsyncSessionLocal() as session:
        b = Ban(chat_id=chat_id, user_id=target, issued_by=issuer, reason=reason, until=until_dt, active=True)
        session.add(b)
        await session.commit()
        await session.refresh(b)
        try:
            await message.bot.ban_chat_member(chat_id, target, until_date=until_dt)
        except Exception:
            pass
        link = await format_user_link(chat_id, target, message.bot, session)
    until_text = until_dt.strftime("%H:%M:%S %d.%m.%Y") if until_dt else "без срока"
    await message.reply(f"<b>{link} заблокирован до {until_text}.</b>\nПричина: {reason or 'Причина не указана'}", parse_mode="HTML")

# ----------------- unban -----------------

@router.message(lambda message: message.text and re.match(r"^(-бан|-?unban|разбан|разблокировать)\b", message.text.strip(), re.IGNORECASE))
async def cmd_unban(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    chat_id = message.chat.id
    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user.id
    else:
        if len(parts) >= 2:
            token = parts[1].split()[0]
            if token.isdigit():
                target = int(token)
            elif token.startswith("@"):
                uid, _ = await try_resolve_username_to_id(chat_id, token, message.bot)
                if uid:
                    target = uid
    if not target:
        await message.reply("<b>Пожалуйста, ответьте на сообщение пользователя или укажите его id.</b>", parse_mode="HTML")
        return
    issuer = message.from_user.id
    role = await get_effective_role(chat_id, issuer, message.bot)
    if role is None or role < 3:
        await message.reply("<b>Ошибка: у вас нет прав снимать баны.</b>", parse_mode="HTML")
        return
    async with AsyncSessionLocal() as session:
        stmt = select(Ban).where(Ban.chat_id == chat_id, Ban.user_id == target, Ban.active == True).order_by(desc(Ban.created_at)).limit(1)
        result = await session.execute(stmt)
        ban_to_remove = result.scalars().first()
        link = await format_user_link(chat_id, target, message.bot, session)
        if ban_to_remove:
            ban_to_remove.active = False
            await session.commit()
            try:
                await message.bot.unban_chat_member(chat_id, target)
            except Exception:
                pass
            await message.reply(f"<b>С {link} был снят бан.</b>", parse_mode="HTML")
        else:
            await message.reply(f"Информация: у пользователя {link} нет активных банов.", parse_mode="HTML")

# ----------------- kick -----------------

@router.message(lambda message: message.text and re.match(r"^(?:\+кик|кик|кикнуть|kick|kicked)\b", message.text.strip(), re.IGNORECASE))
async def cmd_kick(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    issuer = message.from_user.id
    chat_id = message.chat.id
    role = await get_effective_role(chat_id, issuer, message.bot)
    if role is None or role != 5:
        await message.reply("<b>Только владелец может кикать пользователей.</b>", parse_mode="HTML")
        return
    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user.id
    else:
        if len(parts) >= 2:
            token = parts[1].split()[0]
            if token.isdigit():
                target = int(token)
            elif token.startswith("@"):
                uid, _ = await try_resolve_username_to_id(chat_id, token, message.bot)
                if uid:
                    target = uid
    if not target:
        await message.reply("<b>Пожалуйста, ответьте на сообщение пользователя или укажите его id.</b>", parse_mode="HTML")
        return

    # Проверка, присутствует ли пользователь (если он уже ушёл/кикнут, нет смысла кикать)
    present, status = await is_user_present_in_chat(chat_id, target, message.bot)
    async with AsyncSessionLocal() as session:
        link = await format_user_link(chat_id, target, message.bot, session)
    if not present:
        await message.reply(f"<b>Невозможно кикнуть {link}: пользователь уже вышел или был удалён/забанен.</b>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as session:
        try:
            await message.bot.ban_chat_member(chat_id, target)
            await message.bot.unban_chat_member(chat_id, target)
        except Exception:
            pass
        link = await format_user_link(chat_id, target, message.bot, session)
    await message.reply(f"<b>{link} был удалён из группы.</b>", parse_mode="HTML")
