"""Tables. Times are stored as epoch seconds (UTC) so comparisons are simple and timezone-proof."""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    initials: Mapped[str] = mapped_column(String(8), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change: Mapped[bool] = mapped_column(Boolean, default=True)           # true while a temporary password is in use
    temp_expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    password_changed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Device(Base):
    __tablename__ = "devices"
    initials: Mapped[str] = mapped_column(ForeignKey("users.initials"), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    first_seen: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[str] = mapped_column(String(40), index=True)
    initials: Mapped[str] = mapped_column(ForeignKey("users.initials"), index=True)
    device_id: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)           # only the hash is stored
    status: Mapped[str] = mapped_column(String(10), default="active")          # active | used | revoked
    scope: Mapped[str] = mapped_column(String(12), default="full")             # full | pwd_change
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    absolute_expires_at: Mapped[float] = mapped_column(Float)
    used_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AuthEvent(Base):
    """Sign-in audit trail. Never contains passwords."""
    __tablename__ = "auth_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    utc: Mapped[float] = mapped_column(Float, index=True)
    initials: Mapped[str] = mapped_column(String(8), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    device_id: Mapped[str] = mapped_column(String(64), default="")
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(200), default="")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("date", "serial", name="uq_run_date_serial"),)
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_code: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[str] = mapped_column(String(6))
    serial: Mapped[int] = mapped_column(Integer)
    package: Mapped[str] = mapped_column(String(16), default="")
    created_by: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[float] = mapped_column(Float)
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_run", "run_code", "utc"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)              # client-made UUID: makes uploads idempotent
    run_code: Mapped[str] = mapped_column(ForeignKey("runs.code"))
    actor: Mapped[str] = mapped_column(String(8))                              # always the token's owner, never client-supplied
    type: Mapped[str] = mapped_column(String(32))
    utc: Mapped[str] = mapped_column(String(40))
    data: Mapped[str] = mapped_column(Text, default="{}")
    received_at: Mapped[float] = mapped_column(Float)
