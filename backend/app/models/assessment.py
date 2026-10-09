"""Попытки тестирования и ответы."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow

ATTEMPT_STATUSES = ("in_progress", "finished")


class Attempt(Base):
    """
    Попытка теста.

    items и keys — серверная часть собранного теста (с item_id, сложностью и
    ключами проверки); наружу уходит только client_items. Хранение ключей
    в попытке делает её независимой от последующих изменений банка.
    """

    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    specialization: Mapped[str] = mapped_column(String(20))
    declared_level: Mapped[str] = mapped_column(String(10))
    seed: Mapped[int] = mapped_column(BigInteger, unique=True)
    bank_version: Mapped[str] = mapped_column(String(20))
    test_label: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finish_reason: Mapped[str | None] = mapped_column(String(20))  # submitted | expired | demo_autofill

    items: Mapped[list] = mapped_column(default=list)
    keys: Mapped[list] = mapped_column(default=list)
    client_items: Mapped[list] = mapped_column(default=list)

    score: Mapped[int | None] = mapped_column(Integer)
    points_earned: Mapped[int | None] = mapped_column(Integer)
    points_possible: Mapped[int | None] = mapped_column(Integer)
    confirmed_level: Mapped[str | None] = mapped_column(String(15))
    outcome: Mapped[str | None] = mapped_column(String(15))
    result: Mapped[dict | None] = mapped_column()  # документ результата банка (спецификация банка, раздел 6)
    # компактная выжимка результата для подбора: полосы сложности и решение о грейде;
    # подбор читает только её и не разбирает тяжёлые items/keys/result
    summary: Mapped[dict | None] = mapped_column()
    applied: Mapped[dict | None] = mapped_column()  # как результат изменил грейд
    flags: Mapped[list] = mapped_column(default=list)  # признаки для ручного разбора
    # сигналы браузера во время попытки: {"focus_lost": n, "copy": n, "paste": n}
    signals: Mapped[dict] = mapped_column(default=dict)

    __table_args__ = (
        Index("ix_attempts_user_started", "user_id", "started_at"),
        Index("ix_attempts_cohort", "specialization", "declared_level", "status"),
        # одна активная попытка на пользователя — на уровне БД, а не только проверкой в коде:
        # два одновременных «Начать тест» не создадут две попытки
        Index("uq_attempts_one_active", "user_id", unique=True,
              sqlite_where=text("status = 'in_progress'"), postgresql_where=text("status = 'in_progress'")),
    )


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(20), index=True)
    variant_id: Mapped[str] = mapped_column(String(10))
    competency: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[int] = mapped_column(Integer)
    submitted: Mapped[dict | None] = mapped_column()  # {"value": ...}
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_correct: Mapped[bool | None] = mapped_column()
    # ответ в виде, не зависящем от перестановки вариантов (хеш текста) — для антиплагиата
    answer_key: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (Index("ix_attempt_answers_item_key", "item_id", "variant_id", "answer_key"),)
