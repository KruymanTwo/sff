import re
from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from db import AsyncSessionLocal
from models import RoleAssignment, Nick

router = Router()

ROLE_MAP = {
    5: "👑 Владелец",
    4: "🛡 Администратор",
    3: "⚔️ Мл. Администратор",
    2: "👮‍♂️ Модератор",
    1: "🔎 Мл. Модератор"
}

ROLE_NAMES = {
    "владелец": 5, "owner": 5, "create": 5,
    "администратор": 4, "админ": 4, "admin": 4,
    "мл.администратор": 3, "младмин": 3, "мл.админ": 3,
    "модератор": 2, "модер": 2, "mod": 2,
    "мл.модератор": 1, "мл.модер": 1, "хелпер": 1, "helper": 1
}


async def format_user_link(chat_id: int, user_id: int, bot, session):
    try:
        q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == user_id))
        nick = q.scalars().first()
        if nick:
            display = nick.nick
        else:
            member = await bot.get_chat_member(chat_id, user_id)
            display = member.user.full_name
        return f'<a href="tg://user?id={user_id}">{display}</a>'
    except Exception:
        return f'<a href="tg://user?id={user_id}">{user_id}</a>'


@router.message(
    F.text.lower().in_({"?админ", "админы", "?админы", "admins", "/staff", "/admins", "список администрации"}))
async def cmd_staff_list(message: Message):
    chat_id = message.chat.id

    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(RoleAssignment)
            .where(RoleAssignment.chat_id == chat_id)
            .order_by(RoleAssignment.role_id.desc())
        )
        all_staff = q.scalars().all()

        grouped_roles = {5: [], 4: [], 3: [], 2: [], 1: []}

        for staff_member in all_staff:
            if staff_member.role_id in grouped_roles:
                link = await format_user_link(chat_id, staff_member.user_id, message.bot, session)
                grouped_roles[staff_member.role_id].append(link)

    lines = ["<b>🍊 Список администраторов</b>\n"]
    has_staff = False

    for role_id in [5, 4, 3, 2, 1]:
        users = grouped_roles[role_id]
        if users:
            has_staff = True
            role_name = ROLE_MAP.get(role_id, "Роль")
            lines.append(f"<b>[{role_id}] {role_name}</b>")
            for user_link in users:
                lines.append(f" • {user_link}")
            lines.append("")

    if not has_staff:
        await message.reply("ℹ️ <b>В этом чате список администрации пуст.</b>", parse_mode="HTML")
    else:
        await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(F.text.regexp(r"(?i)^(\+|!|/)?(админ|назначить|повысить|setrole|promote)\b"))
async def cmd_promote(message: Message):
    parts = message.text.strip().split()
    issuer_id = message.from_user.id
    chat_id = message.chat.id

    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer_id))
        issuer_role = q.scalars().first()

    issuer_level = issuer_role.role_id if issuer_role else 0

    # Разрешаем только Владельцу (ID 5)
    if issuer_level != 5:
        await message.reply("<b>Только Владелец может назначать администраторов.</b>", parse_mode="HTML")
        return

    target_id = None
    role_arg = None

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        if len(parts) > 1:
            role_arg = parts[1].lower()
    else:
        if len(parts) >= 3:
            if parts[1].isdigit():
                target_id = int(parts[1])
            role_arg = parts[2].lower()

    if not target_id or not role_arg:
        await message.reply(
            "<b>Используйте эту команду правильно:</b>\n<code>+повысить [id роли]</code>",
            parse_mode="HTML")
        return

    new_role_id = ROLE_NAMES.get(role_arg) or (int(role_arg) if role_arg.isdigit() else None)

    if not new_role_id or new_role_id not in ROLE_MAP:
        await message.reply(f"<b>Неизвестная роль.</b>\nДоступные: {', '.join([str(k) for k in ROLE_MAP.keys()])}",
                            parse_mode="HTML")
        return

    # Владелец не может выдать роль 5 (другого владельца) через эту команду, если нужно - можно убрать проверку
    if new_role_id >= issuer_level:
        await message.reply("<b>Вы не можете выдать роль выше или равную своей.</b>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as session:
        q_target = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == target_id))
        existing_role = q_target.scalars().first()

        target_link = await format_user_link(chat_id, target_id, message.bot, session)
        role_title = ROLE_MAP[new_role_id]

        if existing_role:
            existing_role.role_id = new_role_id
            action_text = "обновлена"
        else:
            new_assignment = RoleAssignment(chat_id=chat_id, user_id=target_id, role_id=new_role_id)
            session.add(new_assignment)
            action_text = "выдана"

        await session.commit()

    await message.reply(
        f"Пользователю {target_link} {action_text} роль: <b>{role_title}</b> <code>[{new_role_id}]</code>",
        parse_mode="HTML")


@router.message(F.text.regexp(r"(?i)^(\+|!|/)?(снять|разжаловать|demote|unrole)\b"))
async def cmd_demote(message: Message):
    parts = message.text.strip().split()
    issuer_id = message.from_user.id
    chat_id = message.chat.id

    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == issuer_id))
        issuer_role = q.scalars().first()

    issuer_level = issuer_role.role_id if issuer_role else 0

    # Разрешаем только Владельцу (ID 5) снимать роли
    if issuer_level != 5:
        await message.reply("<b>Только Владелец может снимать роли.</b>", parse_mode="HTML")
        return

    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1 and parts[1].isdigit():
        target_id = int(parts[1])

    if not target_id:
        await message.reply("<b>Укажите пользователя.</b>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as session:
        q_target = await session.execute(
            select(RoleAssignment).where(RoleAssignment.chat_id == chat_id, RoleAssignment.user_id == target_id))
        existing_role = q_target.scalars().first()

        target_link = await format_user_link(chat_id, target_id, message.bot, session)

        if not existing_role:
            await message.reply(f"У {target_link} нет роли.", parse_mode="HTML")
            return

        await session.delete(existing_role)
        await session.commit()

    await message.reply(f"🗑 Роль у пользователя {target_link} была снята.", parse_mode="HTML")