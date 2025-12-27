import re
from aiogram import Router, F
from aiogram.types import Message
from db import AsyncSessionLocal
from models import Nick
from sqlalchemy import select
from config import cfg

router = Router()


@router.message(lambda message: message.text and re.match(r"^-ник\b", message.text.strip(), re.IGNORECASE))
async def cmd_del_nick(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == user_id))
        existing = q.scalars().first()

        if existing:
            await session.delete(existing)
            await session.commit()
            await message.reply("🗑 Ваш ник был удален.", parse_mode="HTML")
        else:
            await message.reply("У вас и так нет установленного ника.", parse_mode="HTML")


@router.message(lambda message: message.text and (
        re.match(r"^\+ник\b", message.text.strip(), re.IGNORECASE) or
        re.match(r"^ник\s+\S+", message.text.strip(), re.IGNORECASE)
))
async def cmd_set_nick(message: Message):
    parts = message.text.strip().split(maxsplit=1)

    # Если ввели просто "+ник" без имени
    if len(parts) < 2:
        await message.reply("Использование: ник [новое имя] или +ник [новое имя]", parse_mode="HTML")
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.reply("Ник не может быть пустым.", parse_mode="HTML")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == user_id))
        existing = q.scalars().first()

        if existing:
            existing.nick = new_nick
            session.add(existing)
        else:
            n = Nick(chat_id=chat_id, user_id=user_id, nick=new_nick)
            session.add(n)
        await session.commit()

    user_link = f'<a href="tg://user?id={user_id}">{new_nick}</a>'
    await message.reply(f"✅ Имя изменено на {user_link}!", parse_mode="HTML")


@router.message(lambda message: message.text and re.match(r"^(\?ник|ник)\b", message.text.strip(), re.IGNORECASE))
async def cmd_get_nick(message: Message):
    parts = message.text.strip().split()
    chat_id = message.chat.id
    target_user_id = None
    target_name_fallback = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name_fallback = message.reply_to_message.from_user.full_name

    elif len(parts) > 1:
        arg = parts[1]

        if message.entities:
            for entity in message.entities:
                if entity.type == "text_mention" and entity.user:
                    target_user_id = entity.user.id
                    target_name_fallback = entity.user.full_name
                    break
                elif entity.type == "mention" and arg.startswith("@"):

                    try:

                        username = arg.lstrip("@")
                        pass
                    except Exception:
                        pass

        # Если ID не найден через entities, пробуем числовой ID
        if not target_user_id and arg.isdigit():
            target_user_id = int(arg)

        # Если всё еще нет ID и это похоже на @username, попробуем найти в чате (может вызвать ошибку, если юзера нет)
        if not target_user_id and arg.startswith("@"):
            await message.reply(
                "Для просмотра ника по @username, боту сложно определить ID. Пожалуйста, <b>ответьте</b> на сообщение пользователя командой <code>?ник</code>.",
                parse_mode="HTML")
            return


    else:
        target_user_id = message.from_user.id
        target_name_fallback = message.from_user.full_name


    if not target_user_id:
        await message.reply("Не удалось определить пользователя. Ответьте на сообщение или укажите ID.",
                            parse_mode="HTML")
        return

    # ЗАПРОС К БАЗЕ
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == target_user_id))
        existing = q.scalars().first()

        # Если просматриваем СЕБЯ
        if target_user_id == message.from_user.id:
            if existing:
                user_link = f'<a href="tg://user?id={target_user_id}">{existing.nick}</a>'
                await message.reply(f"🍊 Вас зовут {user_link}.", parse_mode="HTML")
            else:
                user_link = f'<a href="tg://user?id={target_user_id}">{target_name_fallback}</a>'
                await message.reply(f"🍊 Вас зовут {user_link}. (Ник не установлен)", parse_mode="HTML")

        # Если просматриваем ДРУГОГО
        else:
            if existing:
                user_link = f'<a href="tg://user?id={target_user_id}">{existing.nick}</a>'
                await message.reply(f"Это пользователь {user_link}.", parse_mode="HTML")
            else:
                if not target_name_fallback:
                    try:
                        member = await message.bot.get_chat_member(chat_id, target_user_id)
                        target_name_fallback = member.user.full_name
                    except Exception:
                        target_name_fallback = "Пользователь"

                user_link = f'<a href="tg://user?id={target_user_id}">{target_name_fallback}</a>'
                await message.reply(f"Это пользователь {user_link}. (Ник не установлен)", parse_mode="HTML")
