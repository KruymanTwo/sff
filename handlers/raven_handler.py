
import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from config import cfg

router = Router()

@router.message(Command(commands=["send_raven_bot"]))
async def cmd_send_raven_bot(message: Message):

    caller_id = message.from_user.id
    if caller_id not in cfg.CREATOR_IDS:
        await message.reply("Команда доступна только создателям бота.", parse_mode=cfg.PARSE_MODE)
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        await message.reply(
            "Использование: /send_raven_bot [ссылка] [текст]\n"
            "Пример: /send_raven_bot https://t.me/c/3413026178/1 Привет всем",
            parse_mode=cfg.PARSE_MODE,
        )
        return

    link = parts[1].strip()
    text = parts[2].strip()
    if not link:
        await message.reply("Без указания ссылки нельзя отправлять сообщения!", parse_mode=cfg.PARSE_MODE)
        return
    if not text:
        await message.reply("Текст сообщения не может быть пустым.", parse_mode=cfg.PARSE_MODE)
        return

    m = re.search(r"(?:https?:\/\/)?t\.me\/c\/(\d+)\/\d+", link)
    if not m:
        await message.reply(
            "Неверная ссылка. Поддерживается только формат: https://t.me/c/<chat_short_id>/<msg_id>",
            parse_mode=cfg.PARSE_MODE,
        )
        return

    short_id = m.group(1)

    try:
        chat_id = int(f"-100{short_id}")
    except Exception:
        await message.reply("Не удалось преобразовать id чата из ссылки.", parse_mode=cfg.PARSE_MODE)
        return

    try:
        await message.bot.send_message(chat_id, text, parse_mode=cfg.PARSE_MODE)
        await message.reply("✅ Сообщение отправлено.", parse_mode=cfg.PARSE_MODE)
    except Exception as e:

        await message.reply(f"Ошибка при отправке сообщения: {e}", parse_mode=cfg.PARSE_MODE)