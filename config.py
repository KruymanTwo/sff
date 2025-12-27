import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///woxl.db")
    PARSE_MODE: str = "HTML"

    CREATOR_IDS_RAW: str = os.getenv("CREATOR_IDS", "")

    @property
    def CREATOR_IDS(self):
        s = self.CREATOR_IDS_RAW or ""
        ids = set()
        for part in s.split(","):
            part = part.strip()
            if not part:
                continue
            if part.lstrip().isdigit():
                try:
                    ids.add(int(part))
                except ValueError:
                    pass
        return ids


cfg = Config()

if not cfg.BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Please set BOT_TOKEN env var.")