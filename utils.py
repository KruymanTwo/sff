import re
from datetime import datetime
from typing import Optional, Union
from dateutil.relativedelta import relativedelta

_time_regex = re.compile(r"(?P<num>\d+)\s*(?P<unit>y|g|mon|мес|w|н|d|д|h|ч|m|м|s|с)$", re.IGNORECASE)


def parse_duration(text: str) -> Optional[relativedelta]:
    s = text.strip().lower()
    m = _time_regex.match(s)
    if not m:
        return None

    num = int(m.group("num"))
    unit = m.group("unit")

    # Используем только relativedelta для единообразия
    units_map = {
        ('s', 'с'): 'seconds',
        ('m', 'м'): 'minutes',
        ('h', 'ч'): 'hours',
        ('d', 'д'): 'days',
        ('w', 'н'): 'weeks',
        ('mon', 'мес'): 'months',
        ('y', 'г'): 'years'
    }

    for keys, attr in units_map.items():
        if unit in keys:
            return relativedelta(**{attr: num})
    return None


def format_timedelta_remaining(until_dt: datetime) -> str:
    # ИСПРАВЛЕНИЕ: используем .now() без utcnow, чтобы часовые пояса совпали
    now = datetime.now()
    diff = until_dt - now

    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "закончено"

    days, seconds = divmod(total_seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days: parts.append(f"{days}д")
    if hours: parts.append(f"{hours}ч")
    if minutes: parts.append(f"{minutes}м")
    if not parts: parts.append(f"{seconds}с")

    return " ".join(parts)