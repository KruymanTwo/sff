import logging
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommandScopeDefault, BotCommand
from aiogram import types

from config import cfg
from db import init_db
from handlers.start_handler import router as start_router
from handlers.roles_handler import router as roles_router
from handlers.nicks_handler import router as nicks_router
from handlers.warns_handler import router as warns_router
from handlers.raven_handler import router as raven_router
from handlers.moderation_handler import router as moderation_router
from handlers.ping_handler import router as ping_router
from db import AsyncSessionLocal
from models import Chat, RoleAssignment
from sqlalchemy import select
from datetime import datetime
from handlers.new_year_handler import router as new_year_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=cfg.BOT_TOKEN)
dp = Dispatcher()

START_TIME = datetime.utcnow()

dp.include_router(start_router)
dp.include_router(roles_router)
dp.include_router(nicks_router)
dp.include_router(warns_router)
dp.include_router(raven_router)
dp.include_router(moderation_router)
dp.include_router(ping_router)
dp.include_router(new_year_router)


@dp.my_chat_member()
async def on_my_chat_member(update: types.ChatMemberUpdated):

    try:

        chat = update.chat
        if chat is None:
            return

        async with AsyncSessionLocal() as session:
            q = await session.execute(select(Chat).where(Chat.id == chat.id))
            ch = q.scalars().first()
            if not ch:
                ch = Chat(id=chat.id)
                session.add(ch)
                await session.commit()

        try:
            admins = await bot.get_chat_administrators(chat.id)
        except Exception as e:
            logger.exception("Could not get chat administrators for chat %s: %s", chat.id, e)
            return

        owner = None
        for a in admins:

            if getattr(a, "status", "").lower() == "creator":
                owner = a.user
                break

        if owner:
            async with AsyncSessionLocal() as session:
                q = await session.execute(select(RoleAssignment).where(RoleAssignment.chat_id == chat.id, RoleAssignment.user_id == owner.id))
                existing = q.scalars().first()
                if existing:
                    existing.role_id = 5
                    session.add(existing)
                else:
                    ra = RoleAssignment(chat_id=chat.id, user_id=owner.id, role_id=5, assigned_by=None)
                    session.add(ra)
                await session.commit()
                logger.info("Assigned owner role in chat %s to user %s", chat.id, owner.id)
    except Exception as e:
        logger.exception("Error in on_my_chat_member: %s", e)


async def main():

    await init_db()

    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="admins", description="Показать список админов"),
        BotCommand(command="ping", description="Пинг и информация")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import asyncio
    import sys
    import time
    import os

    try:
        asyncio.run(main())
    except KeyboardInterrupt:

        sys.stderr.write("\nОстановка бота...\n")
    finally:

        sys.stdout.flush()
        sys.stderr.flush()

        os._exit(0)