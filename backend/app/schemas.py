"""Общие схемы ответов API (используются в OpenAPI)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.reference import INDUSTRIES, LEVELS, SKILLS, SPECIALIZATIONS, TEAM_ROLES, TRACKS, WORK_FORMATS

Specialization = Literal["backend", "frontend", "qa"]
Level = Literal["junior", "middle", "senior"]
WorkFormat = Literal["office", "hybrid", "remote"]


class Ref(BaseModel):
    slug: str
    title: str


class Factor(BaseModel):
    factor: str = Field(description="competencies | test | stack | fsp | freshness")
    title: str
    value: float = Field(description="Значение фактора 0..1")
    weight: float
    contribution: float = Field(description="Вклад в итоговый балл (из 100)")
    text: str = Field(description="Объяснение для работодателя")


class PenaltyReason(BaseModel):
    title: str = Field(description="Что не совпало")
    points: float = Field(description="Сколько баллов стоила эта причина")


class Match(BaseModel):
    score: float = Field(description="Итоговый балл 0..100")
    base_score: float | None = None
    penalty: float | None = Field(
        None, description="Доля снижения за условия (зарплата, формат, город)"
    )
    penalty_reasons: list[PenaltyReason] = Field(
        default_factory=list, description="Из чего сложилось снижение"
    )
    factors: list[Factor]
    highlights: list[str]
    warnings: list[str]
    category_role: str | None = None


class CompetencyRow(BaseModel):
    competency: str
    title: str
    estimate: float = Field(description="Сглаженная оценка 0..1")
    raw_rate: float = Field(description="Доля баллов без сглаживания")
    items: int
    confidence: float
    confidence_label: str


class CategoryOut(BaseModel):
    specialization: str = Field(description="IT-направление (отрасль)")
    specialization_title: str
    track: str | None = Field(None, description="Специализация внутри направления")
    track_title: str | None = None
    level: str = Field(description="Подтверждённый грейд или, если confirmed=false, заявленный")
    confirmed: bool = Field(True, description="Грейд подтверждён тестом")
    status: str = Field("confirmed", description="confirmed | not_tested | not_confirmed | decision_pending")
    status_title: str = "подтверждён тестом"
    confirmed_at: datetime | None = None


class TestSummary(BaseModel):
    score: int | None
    declared_level: str | None
    finished_at: datetime | None
    level_band_rate: float
    level_band_detail: list[dict]
    percentile_in_category: float
    attempts_total: int
    grade_decision: dict | None = None
    flags: list[dict] = Field(
        default_factory=list,
        description="Признаки для разбора по определяющей попытке (прокторинг, совпадение ошибок с другой "
                    "попыткой): code и message. На грейд не влияют",
    )


class FspAchievementOut(BaseModel):
    event_name: str
    discipline: str
    discipline_title: str
    event_level: str
    event_level_title: str
    result: str
    result_title: str
    place: int | None
    team_role: str | None
    team_name: str | None
    event_date: str
    verified: bool
    certificate_url: str | None = None
    weight: float | None = None


class FspBlock(BaseModel):
    linked: bool | None
    hidden_by_candidate: bool
    score: float | None
    headline: str | None
    achievements: list[FspAchievementOut]
    note: str | None = None


class Contacts(BaseModel):
    full_name: str | None
    email: str | None
    phone: str | None
    telegram: str | None


class CandidateCard(BaseModel):
    candidate_id: str = Field(description="Псевдоним кандидата (public_id)")
    display_name: str
    city: str | None
    relocation: bool
    category: CategoryOut
    test: TestSummary
    competencies: list[CompetencyRow]
    stack: list[Ref]
    experience_years: float | None
    roles: list[Ref]
    work_formats: list[Ref]
    salary_expectation: int | None
    open_to_offers: bool
    minor: bool = Field(False, description="Кандидату меньше 18 лет (дата рождения не раскрывается)")
    minor_note: str | None = Field(None, description="Что это значит для работодателя")
    last_active_at: datetime | None
    fsp: FspBlock
    regular_tasks: dict
    contacts: Contacts | None
    contacts_visible: bool
    contacts_note: str
    about: str | None = None
    soft_skills: list[str] | None = None
    other_categories: list[CategoryOut] = Field(
        default_factory=list, description="Категории кандидата в других направлениях (только в карточке кандидата)")


class SearchItem(BaseModel):
    candidate: CandidateCard
    ranking: Match


class SearchOut(BaseModel):
    total: int
    items: list[SearchItem]


class SelectionRow(BaseModel):
    rank: int
    candidate_id: str
    candidate: CandidateCard
    match: Match


class SelectionOut(BaseModel):
    id: str
    need_id: str | None
    parent_id: str | None
    params: dict
    summary: dict
    results: list[SelectionRow]
    created_at: datetime
    chain: list[dict] = Field(default_factory=list, description="Цепочка уточнений от исходной подборки")
    unavailable: int = Field(0, description="Сколько кандидатов подборки больше недоступны (закрыли профиль или удалили учётную запись)")


class VacancyCompany(BaseModel):
    id: str
    name: str
    industry: str | None
    city: str | None


class VacancyOut(BaseModel):
    id: str
    title: str
    company: VacancyCompany
    specialization: str
    specialization_title: str
    level: str
    description: str
    team_description: str | None
    stack: list[Ref]
    work_format: str
    work_format_title: str
    city: str | None
    salary_from: int
    salary_to: int
    salary_basis: str = Field(description="gross — до вычета НДФЛ")
    salary_note: str
    status: str
    suitable_for_minors: bool = Field(description="Подходит для несовершеннолетних (15–17 лет)")
    published_at: str | None


class ThreadMessageOut(BaseModel):
    id: str
    sender: str = Field(description="candidate | employer")
    mine: bool
    body: str
    created_at: datetime
    read_at: datetime | None


class TextOut(BaseModel):
    message: str


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000, description="Текст сообщения")

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Сообщение пустое")
        return v.strip()


class SalaryRange(BaseModel):
    salary_from: int = Field(gt=0, description="Нижняя граница, ₽ в месяц до вычета НДФЛ")
    salary_to: int = Field(gt=0, description="Верхняя граница, ₽ в месяц до вычета НДФЛ")

    @model_validator(mode="after")
    def _order(self):
        if self.salary_from > self.salary_to:
            raise ValueError("нижняя граница зарплаты больше верхней")
        return self


def check_skills(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    unknown = [v for v in values if v not in SKILLS]
    if unknown:
        raise ValueError("неизвестные навыки: " + ", ".join(unknown[:5]))
    return list(dict.fromkeys(values))


def check_formats(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    unknown = [v for v in values if v not in WORK_FORMATS]
    if unknown:
        raise ValueError("неизвестные форматы работы: " + ", ".join(unknown))
    return list(dict.fromkeys(values))


def check_roles(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    unknown = [v for v in values if v not in TEAM_ROLES]
    if unknown:
        raise ValueError("неизвестные роли: " + ", ".join(unknown))
    return list(dict.fromkeys(values))


class SurveyIn(BaseModel):
    """
    Опрос по отрасли и специализации. Отрасль в ТЗ — IT-направление
    (`specialization`: backend, frontend, qa), специализация — `track`
    внутри направления (Python, React, автоматизация…). Предметная область
    (`industry`: финтех, госсектор…) необязательна и на тест не влияет.
    """

    specialization: Specialization = Field(description="IT-направление (отрасль): backend | frontend | qa")
    track: str | None = Field(None, description="Специализация внутри направления из reference.tracks")
    industry: str | None = Field(None, description="Предметная область (необязательно) из reference.industries")
    self_level: Level = Field(description="Предполагаемый грейд по самооценке")
    experience_years: float | None = Field(None, ge=0, le=60)
    stack: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    work_formats: list[str] = Field(default_factory=list)
    goals: str | None = Field(None, max_length=1000)
    birth_date: date | None = Field(
        None,
        description="Дата рождения. Обязательна, если её нет в профиле (`birth_date_required`): от возраста зависят "
                    "правила для 14–17 лет. Работодатель видит только отметку «до 18 лет»",
    )

    @field_validator("birth_date")
    @classmethod
    def _birth_date(cls, v):
        from app.services.minors import check_birth_date

        return check_birth_date(v)

    @field_validator("industry")
    @classmethod
    def _industry(cls, v):
        if v is not None and v not in INDUSTRIES:
            raise ValueError("неизвестная предметная область")
        return v

    @model_validator(mode="after")
    def _track(self):
        if self.track is not None and self.track not in TRACKS.get(self.specialization, {}):
            raise ValueError("специализация не относится к выбранному направлению")
        return self

    @field_validator("stack")
    @classmethod
    def _stack(cls, v):
        return check_skills(v)

    @field_validator("roles")
    @classmethod
    def _roles(cls, v):
        return check_roles(v)

    @field_validator("work_formats")
    @classmethod
    def _formats(cls, v):
        return check_formats(v)


REFERENCE_KEYS = {"specializations": SPECIALIZATIONS, "levels": LEVELS}
