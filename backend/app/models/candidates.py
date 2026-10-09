"""Профиль кандидата, опрос, грейд с историей и оценки компетенций."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow

DEFAULT_PRIVACY = {
    # контакты (телефон, почта, telegram) раскрываются только после
    # принятия приглашения или собственного отклика — это не настройка
    "show_full_name": False,  # иначе работодатель видит инициалы
    "show_city": True,
    "show_about": True,
    "show_fsp": True,
    "show_experience": True,
}


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    telegram: Mapped[str | None] = mapped_column(String(64))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    city: Mapped[str | None] = mapped_column(String(100))
    about: Mapped[str | None] = mapped_column(Text)
    experience_years: Mapped[float | None] = mapped_column(Float)
    roles: Mapped[list] = mapped_column(default=list)
    stack: Mapped[list] = mapped_column(default=list)
    soft_skills: Mapped[list] = mapped_column(default=list)
    work_formats: Mapped[list] = mapped_column(default=list)
    relocation: Mapped[bool] = mapped_column(default=False)
    salary_expectation: Mapped[int | None] = mapped_column(Integer)
    open_to_offers: Mapped[bool] = mapped_column(default=True)
    industry: Mapped[str | None] = mapped_column(String(40))
    # дата рождения: нужна, чтобы применить правила для 14–17 лет (app/services/minors.py);
    # работодатель видит только отметку «несовершеннолетний», не дату
    birth_date: Mapped[date | None] = mapped_column(Date)
    primary_specialization: Mapped[str | None] = mapped_column(String(20))
    primary_track: Mapped[str | None] = mapped_column(String(30))
    privacy: Mapped[dict] = mapped_column(default=lambda: dict(DEFAULT_PRIVACY))
    resume_filename: Mapped[str | None] = mapped_column(String(255))
    resume_uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resume_suggestions: Mapped[dict | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user = relationship("User", back_populates="candidate_profile")


class GuardianConsent(Base):
    """
    Согласие законного представителя несовершеннолетнего кандидата на показ
    профиля работодателям и обработку данных для подбора. Представитель
    подтверждает его по ссылке из письма; по той же ссылке может отозвать.
    """

    __tablename__ = "guardian_consents"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    guardian_name: Mapped[str] = mapped_column(String(200))
    guardian_email: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | granted | declined | revoked
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Survey(Base):
    """Опрос по отрасли и специализации — обязательный шаг перед тестом."""

    __tablename__ = "surveys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    industry: Mapped[str | None] = mapped_column(String(40))  # предметная область, необязательно
    specialization: Mapped[str] = mapped_column(String(20))  # IT-направление («отрасль» в ТЗ)
    track: Mapped[str | None] = mapped_column(String(30))  # специализация внутри направления
    self_level: Mapped[str] = mapped_column(String(10))
    experience_years: Mapped[float | None] = mapped_column(Float)
    stack: Mapped[list] = mapped_column(default=list)
    roles: Mapped[list] = mapped_column(default=list)
    work_formats: Mapped[list] = mapped_column(default=list)
    goals: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_surveys_user_created", "user_id", "created_at"),)


class CandidateGrade(Base):
    """Текущий подтверждённый грейд кандидата по специализации — основа категории."""

    __tablename__ = "candidate_grades"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    specialization: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(10))
    defining_attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_change_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # «пропуск» на тест уровнем выше без ожидания смены грейда: выдаётся,
    # когда результат превысил заявленный уровень (повышение — только тестом)
    promotion_level: Mapped[str | None] = mapped_column(String(10))
    promotion_until: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("user_id", "specialization"),
        Index("ix_candidate_grades_category", "specialization", "level"),
    )

    # не колонка: в подборе рядом с грейдами бывают и заявленные (ClaimedGrade)
    confirmed = True
    status = "confirmed"


class GradeHistory(Base):
    __tablename__ = "grade_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    specialization: Mapped[str] = mapped_column(String(20))
    from_level: Mapped[str | None] = mapped_column(String(10))
    to_level: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(40))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GradeRecommendation(Base):
    """
    Рекомендация уровня ниже заявленного.

    Грейд не понижается принудительно: кандидат сам принимает рекомендацию
    или проходит тест уровнем ниже.
    """

    __tablename__ = "grade_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    specialization: Mapped[str] = mapped_column(String(20))
    recommended_level: Mapped[str] = mapped_column(String(10))
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolution: Mapped[str | None] = mapped_column(String(20))  # accepted | declined | superseded


class CompetencyEstimate(Base):
    """
    Сглаженная оценка компетенции (см. app/services/competencies.py).

    estimate = (earned + k·p0) / (possible + k), confidence = possible / (possible + k)
    """

    __tablename__ = "competency_estimates"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    specialization: Mapped[str] = mapped_column(String(20), primary_key=True)
    competency: Mapped[str] = mapped_column(String(40), primary_key=True)
    earned: Mapped[int] = mapped_column(Integer)
    possible: Mapped[int] = mapped_column(Integer)
    items: Mapped[int] = mapped_column(Integer)
    raw_rate: Mapped[float] = mapped_column(Float)
    estimate: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
