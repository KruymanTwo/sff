import re
from aiogram import Router
from aiogram.types import Message
from db import AsyncSessionLocal
from models import Nick
from sqlalchemy import select
from config import cfg

router = Router()


@router.message(lambda message: message.text and re.match(r"^ник\b", message.text.strip(), re.IGNORECASE))
async def cmd_set_nick(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: ник [новое имя]", parse_mode=cfg.PARSE_MODE)
        return
    new_nick = parts[1].strip()
    if not new_nick:
        await message.reply("Ник не может быть пустым.", parse_mode=cfg.PARSE_MODE)
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
    await message.reply(f"✅ Имя изменено на {user_link}!", parse_mode=cfg.PARSE_MODE)


@router.message(lambda message: message.text and re.match(r"^(ник|\?ник)\b", message.text.strip(), re.IGNORECASE))
async def cmd_get_nick(message: Message):
    parts = message.text.strip().split()
    chat_id = message.chat.id
    async with AsyncSessionLocal() as session:
        if len(parts) == 1:
            # show own nick
            q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == message.from_user.id))
            existing = q.scalars().first()
            if existing:
                user_link = f'<a href="tg://user?id={message.from_user.id}">{existing.nick}</a>'
                await message.reply(f"🍊 Ваш зовут {user_link}.", parse_mode=cfg.PARSE_MODE)
            else:
                # fallback to telegram name
                try:
                    member = await message.bot.get_chat_member(chat_id, message.from_user.id)
                    name = member.user.full_name
                    user_link = f'<a href="tg://user?id={message.from_user.id}">{name}</a>'
                    await message.reply(f"🍊 Ваш зовут {user_link}.", parse_mode=cfg.PARSE_MODE)
                except Exception:
                    await message.reply("У вас нет ника. Установите с помощью: ник [имя]", parse_mode=cfg.PARSE_MODE)
            return
        # get nick of another user (reply or id)
        target = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user.id
        else:
            token = parts[1]
            if token.startswith("@"):
                # cannot resolve to id without extra API call — ask to reply or provide id
                await message.reply(f"Пожалуйста, ответьте на сообщение пользователя или укажите его id (не @username).", parse_mode=cfg.PARSE_MODE)
                return
            if token.isdigit():
                target = int(token)
        if target:
            q = await session.execute(select(Nick).where(Nick.chat_id == chat_id, Nick.user_id == target))
            existing = q.scalars().first()
            if existing:
                user_link = f'<a href="tg://user?id={target}">{existing.nick}</a>'
                await message.reply(f"Это пользователь {user_link}.", parse_mode=cfg.PARSE_MODE)
            else:
                # fallback to telegram name if possible
                try:
                    member = await message.bot.get_chat_member(chat_id, target)
                    name = member.user.full_name
                    user_link = f'<a href="tg://user?id={target}">{name}</a>'
                    await message.reply(f"Это пользователь {user_link}.", parse_mode=cfg.PARSE_MODE)
                except Exception:
                    await message.reply("У пользователя нет ника.", parse_mode=cfg.PARSE_MODE)
        else:
            await message.reply("Не удалось определить пользователя. Ответьте на сообщение или укажите id.", parse_mode=cfg.PARSE_MODE)