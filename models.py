
from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, DateTime
from datetime import datetime
from db import Base

ROLE_MAP = {
    1: ("Мл. Модератор", ""),
    2: ("Модератор", ""),
    3: ("Старший Модератор", ""),
    4: ("Администратор", ""),
    5: ("Владелец", "")
}

class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = {"extend_existing": True}
    id = Column(BigInteger, primary_key=True)

class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    role_id = Column(Integer, nullable=False)
    assigned_by = Column(BigInteger, nullable=True)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)

class Nick(Base):
    __tablename__ = "nicks"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    nick = Column(String(255), nullable=False)

class Warn(Base):
    __tablename__ = "warns"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    issued_by = Column(BigInteger, nullable=True)
    reason = Column(Text, nullable=True)
    until = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Mute(Base):
    __tablename__ = "mutes"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    issued_by = Column(BigInteger, nullable=True)
    reason = Column(Text, nullable=True)
    until = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Ban(Base):
    __tablename__ = "bans"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    issued_by = Column(BigInteger, nullable=True)
    reason = Column(Text, nullable=True)
    until = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)