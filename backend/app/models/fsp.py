"""Связь с ФСП ID и снимок достижений участника."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class FspLink(Base):
    __tablename__ = "fsp_links"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    fsp_id: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(100))
    sport_rank: Mapped[str | None] = mapped_column(String(10))  # спортивный разряд из реестра (reference.FSP_SPORT_RANKS)
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sync_error: Mapped[str | None] = mapped_column(String(255))


class FspAchievement(Base):
    """
    Достижение из реестра ФСП. Поля выбраны так, чтобы работодатель видел
    проверяемый факт (мероприятие, уровень, место, роль, дата) и чтобы из
    него можно было посчитать вклад в ранжирование.
    """

    __tablename__ = "fsp_achievements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(64))
    event_name: Mapped[str] = mapped_column(String(255))
    discipline: Mapped[str] = mapped_column(String(60))
    event_level: Mapped[str] = mapped_column(String(20))  # international | federal | regional | local
    place: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(20))  # winner | prize | finalist | participant
    team_role: Mapped[str | None] = mapped_column(String(20))  # captain | member | solo
    team_name: Mapped[str | None] = mapped_column(String(120))
    event_date: Mapped[date] = mapped_column(Date)
    verified: Mapped[bool] = mapped_column(default=True)
    certificate_url: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict] = mapped_column(default=dict)

    __table_args__ = (UniqueConstraint("user_id", "external_id"),)


class OidcState(Base):
    """Состояние незавершённого входа или привязки через ФСП ID (state, PKCE, nonce)."""

    __tablename__ = "oidc_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(10), default="link")  # link | login
    # при входе пользователь ещё неизвестен
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # для входа: согласия на обработку ПДн и получение данных ФСП, если аккаунт создаётся
    consent: Mapped[bool] = mapped_column(default=False)
    code_verifier: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(64))
    redirect_after: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
