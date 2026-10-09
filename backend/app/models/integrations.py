"""Интеграция с ATS работодателя: подписки на события (вебхуки) и журнал доставок."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class WebhookEndpoint(Base):
    """
    Адрес ATS, куда платформа отправляет события компании. Секрет нужен для
    подписи запросов (HMAC-SHA256), поэтому хранится в открытом виде и
    показывается работодателю один раз — при создании. В эксплуатации
    секреты выносятся в хранилище секретов.
    """

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(100))
    events: Mapped[list] = mapped_column(default=list)
    description: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class WebhookDelivery(Base):
    """
    Доставка события (transactional outbox): строка пишется в той же
    транзакции, что и само событие, а фоновый диспетчер отправляет её и
    повторяет при ошибке с растущей паузой.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)
