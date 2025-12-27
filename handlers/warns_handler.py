import re
from datetime import datetime
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, update, desc
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
    lambda message: message.text and re.match(r"^(?:\+?пред|\+?варн|\+пред|\+варн)\b", message.text.strip(), re.IGNORECASE))
async def cmd_warn(message: Message):
    parts = message.text.strip().split(maxsplit=2)

    # Если команда вызвана без аргументов и без реплая — показываем справку
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


    if not message.text.strip().lstrip().startswith("+") and not message.reply_to_message:
        help_text = (
            "<b>ℹ️ Похоже, вы хотите узнать, как использовать команду.</b>\n\n"
            "Чтобы выдать предупреждение — используйте <code>+пред</code> или <code>+варн</code>.\n"
            "Если хотите посмотреть справку — напишите просто <code>пред</code> или <code>варн</code> без плюса."
        )
        await message.reply(help_text, parse_mode="HTML")
        return

    issuer = message.from_user.id
    chat_id = message.chat.id


    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
    if not caller_assign or caller_assign.role_id < 1:
        await message.reply("<b>❌ Вы не имеете права выдавать предупреждения.</b>", parse_mode="HTML")
        return

    # target detection
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        token = parts[1]
        if token.startswith("@"):
            await message.reply(
                "<b>Пожалуйста, используйте reply на сообщение пользователя или укажите его id (без @username).</b>",
                parse_mode="HTML")
            return
        if token.isdigit():
            target_id = int(token)
        else:
            await message.reply("<b>Не удалось определить пользователя. Укажите ID или ответьте на сообщение.</b>",
                                parse_mode="HTML")
            return

    # parse time and reason
    time_td = None
    reason = None

    # Логика разбора аргументов (с учётом reply и не-reply случаев)
    if message.reply_to_message:
        # +пред [time] [reason] ответом на сообщение
        if len(parts) >= 2:
            maybe_time = parts[1]
            td = parse_duration(maybe_time)
            if td:
                time_td = td
                if len(parts) == 3:
                    reason = parts[2]
            else:
                # Если первый аргумент не парсится как длительность — считаем это причиной
                reason = " ".join(parts[1:])
    else:
        # +пред <id> [time] [reason]  OR +пред <id> <reason>  OR +пред <id> <time>
        # В текущей реализации мы поддерживаем: +пред <id> <time> <reason> и +пред <id> <reason>
        if len(parts) >= 3:
            td = parse_duration(parts[2])
            if td:
                time_td = td
            else:
                # попробуем второй аргумент как время, если не подходит — второй считается временем/причиной в зависимости
                td2 = parse_duration(parts[1])
                if td2:
                    time_td = td2
                    reason = " ".join(parts[2:])
                else:
                    reason = " ".join(parts[2:])
        elif len(parts) == 2:
            # +пред <id> — нет времени/причины
            # или +пред <id_or_time> — если token был id, то это уже обработано; здесь ничего дополнительно не делаем
            pass

    until_dt = None
    if time_td:
        until_dt = datetime.now() + time_td

    async with AsyncSessionLocal() as session:
        w = Warn(chat_id=chat_id, user_id=target_id, issued_by=issuer, reason=reason, until=until_dt, active=True)
        session.add(w)
        await session.commit()
        await session.refresh(w)
        link = await format_user_link(chat_id, target_id, message.bot, session)

    until_text = until_dt.strftime("%H:%M:%S %d.%m.%Y") if until_dt else "без срока"
    await message.reply(f"⚠️ {link} получил предупреждение до <b>{until_text}</b> за: <b>{reason or 'Причина не указана'}</b>.",
                        parse_mode="HTML")


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
        await message.reply("<b>Ответьте на сообщение пользователя или укажите его id.</b>", parse_mode="HTML")
        return

    issuer = message.from_user.id

    async with AsyncSessionLocal() as session:
        # Проверка прав
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer))
        caller_assign = q.scalars().first()
        if not caller_assign or caller_assign.role_id < 1:
            await message.reply("<b>❌ Вы не имеете права снимать предупреждения.</b>", parse_mode="HTML")
            return

        # Ищем только последнее активное предупреждение (по created_at)
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
            await message.reply(f"✅ С {link} было снято 1 предупреждение.", parse_mode="HTML")
        else:
            await message.reply(f"ℹ️ У пользователя {link} нет активных предупреждений.", parse_mode="HTML")


# --- ХЕНДЛЕР СПИСКА ПРЕДУПРЕЖДЕНИЙ ---
@router.message(
    lambda message: message.text and re.match(r"^(\?пред|\?варн)(\s+(\d+))?$", message.text.strip(), re.IGNORECASE))
async def cmd_list_warns(message: Message):
    chat_id = message.chat.id
    text = message.text.strip()
    parts = text.split()
    page = 1
    # Если указан номер страницы в аргументе — используем его
    if len(parts) >= 2 and parts[1].isdigit():
        page = max(1, int(parts[1]))
    per_page = 10

    # Если команда вызвана как reply — показываем предупреждения конкретного игрока
    target_user_id = None
    target_display = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id

    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(
                select(Warn).where(Warn.chat_id == chat_id, Warn.active == True, Warn.user_id == target_user_id)
                .order_by(Warn.created_at.desc()))
            warns = q.scalars().all()
            # получим отображаемое имя для заголовка
            target_display = await format_user_link(chat_id, target_user_id, message.bot, session)
        else:
            q = await session.execute(
                select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
            warns = q.scalars().all()

    total = len(warns)
    if total == 0:
        if target_user_id:
            await message.reply(f"ℹ️ {target_display} не имеет активных предупреждений.", parse_mode="HTML")
        else:
            await message.reply("ℹ️ В чате нет активных предупреждений.", parse_mode="HTML")
        return

    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    page_warns = warns[start:start + per_page]

    text_lines = []
    header = "⚠️ Активные предупреждения"
    if target_user_id:
        header = f"⚠️ Активные предупреждения для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных предупреждений:</b> {total}")
    text_lines.append("├─ <b>Список предупреждений:</b>")

    async with AsyncSessionLocal() as session:
        for idx, w in enumerate(page_warns, start=start + 1):
            rem = format_timedelta_remaining(w.until) if w.until else "без срока"
            link = await format_user_link(chat_id, w.user_id, message.bot, session)
            # Показываем кто выдал предупреждение и причину
            issuer_link = await format_user_link(chat_id, w.issued_by, message.bot, session) if w.issued_by else "Система"
            created = w.created_at.strftime("%d.%m.%Y %H:%M") if getattr(w, "created_at", None) else ""
            text_lines.append(
                f"│   {idx}. {link} — <b>за</b>: {w.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}"
            )

    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="warns")
    await message.reply("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")


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

    # Поддерживаем ту же логику: если сообщение-источник было reply к пользователю,
    # то в навигации остаёмся в контексте этого пользователя.
    target_user_id = None
    target_display = None
    if query.message.reply_to_message and query.message.reply_to_message.from_user:
        target_user_id = query.message.reply_to_message.from_user.id

    async with AsyncSessionLocal() as session:
        if target_user_id:
            q = await session.execute(
                select(Warn).where(Warn.chat_id == chat_id, Warn.active == True, Warn.user_id == target_user_id)
                .order_by(Warn.created_at.desc()))
            warns = q.scalars().all()
            target_display = await format_user_link(chat_id, target_user_id, query.bot, session)
        else:
            q = await session.execute(
                select(Warn).where(Warn.chat_id == chat_id, Warn.active == True).order_by(Warn.created_at.desc()))
            warns = q.scalars().all()

    total = len(warns)
    # Если предупреждений уже нет — НЕ редактируем сообщение и НЕ отправляем текст.
    # Просто закрываем callback, чтобы не показывать лишние уведомления пользователю.
    if total == 0:
        await query.answer()  # silently acknowledge the callback
        return

    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    page_warns = warns[start:start + per_page]

    text_lines = []
    header = "⚠️ Активные предупреждения"
    if target_user_id:
        header = f"⚠️ Активные предупреждения для {target_display}"
    text_lines.append(f"<b>{header}</b>")
    text_lines.append(f"┌─ <b>Всего активных предупреждений:</b> {total}")
    text_lines.append("├─ <b>Список предупреждений:</b>")

    async with AsyncSessionLocal() as session:
        for idx, w in enumerate(page_warns, start=start + 1):
            rem = format_timedelta_remaining(w.until) if w.until else "без срока"
            link = await format_user_link(chat_id, w.user_id, query.bot, session)
            issuer_link = await format_user_link(chat_id, w.issued_by, query.bot, session) if w.issued_by else "Система"
            created = w.created_at.strftime("%d.%m.%Y %H:%M") if getattr(w, "created_at", None) else ""
            text_lines.append(
                f"│   {idx}. {link} — <b>за</b>: {w.reason or 'Причина не указана'}; <b>до</b>: ({rem}); <b>выдал</b>: {issuer_link} {created}"
            )

    text_lines.append(f"└─ <b>Страница:</b> {page}/{total_pages}")
    kb = page_kb(page, prefix="warns")
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")
    except Exception:
        await query.answer("Не удалось обновить сообщение.", show_alert=False)
        return
    await query.answer()
