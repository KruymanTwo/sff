from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from db import AsyncSessionLocal
from models import Chat
from sqlalchemy import select
from config import cfg

router = Router()


@router.message(Command(commands=["start"]))
async def cmd_start(message: Message):
    nickname = message.from_user.full_name
    text = (
        f"🍊 Привет, {nickname}. Вы подключились к Woxl -- Ваш чат менеджер по управлению группой!."
    )
    await message.answer(text, parse_mode=cfg.PARSE_MODE)

    async with AsyncSessionLocal() as session:
        if message.chat:
            q = await session.execute(select(Chat).where(Chat.id == message.chat.id))
            chat = q.scalars().first()
            if not chat:
                chat = Chat(id=message.chat.id)
                session.add(chat)
                await session.commit()