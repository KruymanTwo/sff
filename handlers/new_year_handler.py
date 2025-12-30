from aiogram import Router, types
from datetime import datetime, timedelta
import pytz

router = Router()

COMMANDS = ["нг", "до нг", "до нового года"]

@router.message()
async def new_year_countdown(message: types.Message):
    text = message.text.strip().lower()
    if text not in COMMANDS:
        return

    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)


    year = now.year
    if now.month == 12 and now.day > 31:
        year += 1
    new_year = datetime(year=now.year + 1, month=1, day=1, tzinfo=msk_tz)

    delta: timedelta = new_year - now

    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    await message.answer(
        f"<b>До Нового года осталось:</b>\n"
        f"{days} дн. {hours:02d} ч. {minutes:02d} мин. {seconds:02d} сек. (МСК)", parse_mode="HTML"
    )
