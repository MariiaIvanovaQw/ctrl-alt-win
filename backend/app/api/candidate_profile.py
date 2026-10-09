"""Кабинет кандидата: профиль, опрос, резюме, приватность и согласия."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Forbidden, errors
from app.models import (
    Application,
    Attempt,
    CandidateGrade,
    CandidateProfile,
    Consent,
    EmailToken,
    FspAchievement,
    FspLink,
    GradeHistory,
    GuardianConsent,
    Invitation,
    Message,
    OidcState,
    RefreshToken,
    Survey,
    TaskAssignment,
)
from app.models.candidates import DEFAULT_PRIVACY
from app.reference import SKILLS, SPECIALIZATIONS, track_title
from app.schemas import SurveyIn, check_formats, check_roles, check_skills
from app.security.deps import DB, CurrentCandidate
from app.services import matching, minors
from app.services import tasks as tasks_service
from app.services.cards import build_card, placeholder_facts
from app.services.consents import CONSENT_KINDS, audit, current_consents, set_consent
from app.services.mailer import forget_recipient
from app.services.pdf import render_profile
from app.services.resume import parse_resume

router = APIRouter(prefix="/api/v1/candidate", tags=["Кандидат: профиль"], responses=errors(403))

# В выгрузку данных не попадает то, что раскрывает тест: сид (по нему и банку
# тест собирается заново вместе с ключами), состав и ключи заданий, ответы с
# отметкой верности по каждому заданию. Остаются итоги: балл, уровень,
# компетенции, разбор по полосам сложности и правилам грейда.
EXPORT_HIDDEN_COLUMNS = ("items", "keys", "client_items", "token_hash", "seed")
EXPORT_RESULT_FIELDS = (
    "test_id", "specialization", "declared_level", "confirmed_level", "outcome", "score", "points_earned",
    "points_possible", "competencies", "competency_details", "difficulty_buckets", "grade_decision", "finished_at",
)
# длины колонок профиля: подсказки из резюме длиннее не переносятся
PROFILE_LIMITS = {"full_name": 200, "contact_email": 254, "phone": 40, "telegram": 64, "city": 100}


class ProfileOut(BaseModel):
    public_id: str
    email: str
    full_name: str | None
    phone: str | None
    telegram: str | None
    contact_email: str | None
    city: str | None
    about: str | None
    experience_years: float | None
    roles: list[str]
    stack: list[str]
    soft_skills: list[str]
    work_formats: list[str]
    relocation: bool
    salary_expectation: int | None
    open_to_offers: bool
    industry: str | None
    birth_date: date | None = None
    age: int | None = None
    minor: bool = Field(False, description="Младше 18 лет: действуют правила для несовершеннолетних")
    below_work_age: bool = Field(False, description="Младше 15 лет: доступны только тест и категория, без показа работодателям")
    guardian: dict | None = Field(None, description="Согласие законного представителя: статус, ФИО, почта, даты")
    primary_track: str | None = None
    primary_specialization: str | None
    privacy: dict
    resume_filename: str | None
    resume_uploaded_at: datetime | None
    grades: list[dict]
    completeness: int = Field(description="Заполненность профиля, %")


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    telegram: str | None = Field(None, max_length=64)
    contact_email: EmailStr | None = None
    city: str | None = Field(None, max_length=100)
    about: str | None = Field(None, max_length=3000)
    experience_years: float | None = Field(None, ge=0, le=60)
    roles: list[str] | None = None
    stack: list[str] | None = Field(None, max_length=40)
    soft_skills: list[str] | None = Field(None, max_length=20)
    work_formats: list[str] | None = None
    relocation: bool | None = None
    salary_expectation: int | None = Field(None, ge=0, le=10_000_000)
    open_to_offers: bool | None = None
    birth_date: date | None = Field(None, description="Дата рождения; работодатель видит только отметку «до 18 лет»")

    @field_validator("birth_date")
    @classmethod
    def _birth_date(cls, v):
        return minors.check_birth_date(v)

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

    @field_validator("soft_skills")
    @classmethod
    def _soft(cls, v):
        from app.reference import SOFT_SKILLS

        if v is None:
            return None
        unknown = [x for x in v if x not in SOFT_SKILLS]
        if unknown:
            raise ValueError("неизвестные софт-скиллы: " + ", ".join(unknown[:5]))
        return list(dict.fromkeys(v))


class PrivacyIn(BaseModel):
    show_full_name: bool = False
    show_city: bool = True
    show_about: bool = True
    show_fsp: bool = Field(True, description="Скрытые достижения ФСП не показываются и не дают бонуса в ранжировании")
    show_experience: bool = True


class ConsentIn(BaseModel):
    kind: Literal["pd_processing", "profile_publication", "fsp_data"]
    granted: bool


class ConsentOut(BaseModel):
    kind: str
    title: str
    granted: bool
    version: str | None
    updated_at: datetime | None


class ResumeApplyIn(BaseModel):
    fields: list[str] = Field(max_length=20, description="Какие поля подсказок перенести в профиль")


class ResumeOut(BaseModel):
    suggestions: dict = Field(description="Распознанные поля: {поле: {value, confidence, source}}")


class GuardianOut(BaseModel):
    minor: bool
    guardian: dict | None
    dev_link: str | None = Field(None, description="Только в демо-режиме: ссылка для представителя из письма")


class SurveyOut(BaseModel):
    id: str
    industry: str | None = Field(description="Предметная область (необязательно)")
    specialization: str = Field(description="IT-направление — «отрасль» в ТЗ")
    specialization_title: str
    track: str | None = Field(description="Специализация внутри направления")
    track_title: str | None
    self_level: str
    experience_years: float | None
    stack: list[str]
    roles: list[str]
    work_formats: list[str]
    goals: str | None
    created_at: datetime


class SurveyHistoryOut(BaseModel):
    latest: SurveyOut | None
    history: list[SurveyOut]


class GradeOut(BaseModel):
    specialization: str
    level: str
    assigned_at: datetime
    last_change_at: datetime


class DataExportOut(BaseModel):
    user: dict
    profile: dict
    surveys: list[dict]
    grades: list[dict]
    grade_history: list[dict]
    attempts: list[dict]
    invitations: list[dict]
    applications: list[dict]
    tasks: list[dict]
    fsp_link: list[dict]
    fsp_achievements: list[dict]
    consents: list[dict]
    messages: list[dict]
    guardian_consent: list[dict]


def _profile(db, user) -> CandidateProfile:
    profile = db.get(CandidateProfile, user.id)
    if profile is None:
        profile = CandidateProfile(user_id=user.id, contact_email=user.email)
        db.add(profile)
        db.flush()
    return profile


def _completeness(p: CandidateProfile) -> int:
    checks = [p.full_name, p.city, p.experience_years is not None, p.stack, p.work_formats, p.salary_expectation, p.about,
              p.phone or p.telegram, p.primary_specialization]
    return round(100 * sum(1 for c in checks if c) / len(checks))


def _profile_out(db, user, p: CandidateProfile) -> ProfileOut:
    grades = db.scalars(select(CandidateGrade).where(CandidateGrade.user_id == user.id))
    return ProfileOut(
        public_id=user.public_id,
        email=user.email,
        full_name=p.full_name,
        phone=p.phone,
        telegram=p.telegram,
        contact_email=p.contact_email,
        city=p.city,
        about=p.about,
        experience_years=p.experience_years,
        roles=p.roles or [],
        stack=p.stack or [],
        soft_skills=p.soft_skills or [],
        work_formats=p.work_formats or [],
        relocation=p.relocation,
        salary_expectation=p.salary_expectation,
        open_to_offers=p.open_to_offers,
        industry=p.industry,
        birth_date=p.birth_date,
        age=minors.age(p.birth_date),
        minor=minors.is_minor(p),
        below_work_age=minors.below_work_age(p),
        guardian=minors.guardian_out(db, user.id),
        primary_track=p.primary_track,
        primary_specialization=p.primary_specialization,
        privacy={**DEFAULT_PRIVACY, **(p.privacy or {})},
        resume_filename=p.resume_filename,
        resume_uploaded_at=p.resume_uploaded_at,
        grades=[{"specialization": g.specialization, "level": g.level, "assigned_at": g.assigned_at.isoformat()} for g in grades],
        completeness=_completeness(p),
    )


@router.get("/profile", response_model=ProfileOut, summary="Мой профиль")
def get_profile(user: CurrentCandidate, db: DB):
    """Открытие кабинета — момент «периодически предложить» регулярное задание, если подошёл срок."""
    profile = _profile(db, user)
    tasks_service.offer_due_task(db, user)
    db.commit()
    return _profile_out(db, user, profile)


@router.patch("/profile", response_model=ProfileOut, summary="Изменить профиль (ручное заполнение)")
def update_profile(body: ProfileUpdate, user: CurrentCandidate, db: DB):
    """
    Правка профиля не считается активностью для фактора «актуальность» в
    подборе: иначе его поднимало бы любое сохранение формы. Активность — это
    тест, регулярное задание, ответ на приглашение и отклик.
    """
    profile = _profile(db, user)
    changes = body.model_dump(exclude_unset=True)
    if "birth_date" in changes and changes["birth_date"] is None and profile.birth_date is not None:
        # иначе 15–17-летний кандидат стёр бы дату и обошёл согласие законного представителя
        raise AppError("Дату рождения можно исправить, но не удалить: от неё зависят правила для кандидатов 14–17 лет",
                       code="birth_date_required")
    for field, value in changes.items():
        setattr(profile, field, value)
    minors.on_profile_changed(db, user, profile)
    db.commit()
    return _profile_out(db, user, profile)


class GuardianIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=200, description="ФИО законного представителя")
    email: EmailStr = Field(description="Почта представителя (домен .ru): на неё придёт ссылка для согласия")


@router.get("/guardian", response_model=GuardianOut, summary="Согласие законного представителя (до 18 лет)")
def get_guardian(user: CurrentCandidate, db: DB):
    profile = _profile(db, user)
    db.commit()
    return GuardianOut(minor=minors.is_minor(profile), guardian=minors.guardian_out(db, user.id))


@router.post("/guardian", response_model=GuardianOut, responses=errors(400, 429), summary="Запросить согласие законного представителя")
def request_guardian(body: GuardianIn, user: CurrentCandidate, db: DB):
    """
    Для кандидатов 14–17 лет. Представителю уходит письмо со ссылкой: по ней
    он даёт согласие на показ профиля работодателям и отклики (или отказывает)
    и может отозвать его позже. Повторный запрос заменяет прежнюю ссылку. В
    демо-режиме ссылка возвращается в `dev_link`, чтобы показать сценарий
    без почтового ящика.
    """
    profile = _profile(db, user)
    _row, link = minors.request_guardian_consent(db, user, profile, body.full_name, body.email)
    return GuardianOut(minor=True, guardian=minors.guardian_out(db, user.id),
                       dev_link=link if get_settings().demo_mode else None)


@router.post("/profile/resume", response_model=ResumeOut, responses=errors(400, 413), summary="Загрузить PDF-резюме и получить подсказки")
def upload_resume(user: CurrentCandidate, db: DB, file: UploadFile = File(...)):
    """
    Распознаёт ФИО, контакты, город, стаж, роли, грейд, стек и софт-скиллы.
    Профиль не перезаписывается: подсказки применяются отдельным вызовом
    /profile/resume/apply после проверки кандидатом.
    """
    settings = get_settings()
    data = file.file.read(settings.max_resume_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_resume_mb * 1024 * 1024:
        raise AppError("Файл больше %d МБ" % settings.max_resume_mb, code="file_too_large")
    if not data.startswith(b"%PDF"):
        raise AppError("Ожидается файл PDF", code="not_pdf")
    suggestions = parse_resume(data)
    folder = settings.data_dir / "resumes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("%s.pdf" % user.id)).write_bytes(data)
    profile = _profile(db, user)
    profile.resume_filename = (file.filename or "resume.pdf")[:255]
    profile.resume_uploaded_at = utcnow()
    profile.resume_suggestions = suggestions
    db.commit()
    return ResumeOut(suggestions=suggestions)


@router.post("/profile/resume/apply", response_model=ProfileOut, summary="Применить подсказки из резюме")
def apply_resume(body: ResumeApplyIn, user: CurrentCandidate, db: DB):
    from app.reference import SOFT_SKILLS, TEAM_ROLES

    profile = _profile(db, user)
    suggestions = profile.resume_suggestions or {}
    allowed = {"full_name", "contact_email", "phone", "telegram", "city", "experience_years", "roles", "stack", "soft_skills"}
    known = {"stack": SKILLS, "roles": TEAM_ROLES, "soft_skills": SOFT_SKILLS}
    for field in body.fields:
        if field not in allowed or field not in suggestions:
            continue
        value = suggestions[field]["value"]
        if field in known:
            current = getattr(profile, field) or []
            value = list(dict.fromkeys(current + [v for v in value if v in known[field]]))
        elif isinstance(value, str) and len(value) > PROFILE_LIMITS.get(field, 10_000):
            continue  # распознанное значение не помещается в поле профиля — пусть кандидат введёт вручную
        setattr(profile, field, value)
    db.commit()
    return _profile_out(db, user, profile)


@router.get(
    "/profile/pdf",
    summary="Стандартизированный PDF-профиль",
    responses={200: {"content": {"application/pdf": {}}, "description": "PDF-файл"}},
    response_class=Response,
)
def profile_pdf(user: CurrentCandidate, db: DB):
    """
    PDF доступен и до теста: тогда в нём пометка «категория не присвоена».
    Это личная копия кандидата: в ней все его данные, включая контакты.
    """
    facts = matching.load_facts(db, user_ids=[user.id], only_published=False)
    profile = _profile(db, user)
    if facts:
        spec = profile.primary_specialization
        chosen = next((f for f in facts if f.grade.specialization == spec), facts[0])
    else:
        chosen = placeholder_facts(db, user, profile)
    card = build_card(chosen, contacts_reason="own_copy", full=True, respect_privacy=False)
    card["display_name"] = profile.full_name or card["display_name"]
    pdf = render_profile(card, generated_for="кандидат (личная копия)")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=profile-%s.pdf" % user.public_id})


@router.get("/privacy", response_model=PrivacyIn, summary="Настройки приватности")
def get_privacy(user: CurrentCandidate, db: DB):
    profile = _profile(db, user)
    db.commit()
    return {**DEFAULT_PRIVACY, **(profile.privacy or {})}


@router.put("/privacy", response_model=PrivacyIn, summary="Изменить настройки приватности")
def set_privacy(body: PrivacyIn, user: CurrentCandidate, db: DB):
    """
    Скрытое поле не показывается работодателю нигде: ни в карточке и PDF,
    ни в обосновании выдачи, ни через фильтры поиска. Скрытые достижения ФСП
    не дают бонуса в ранжировании (иначе их пришлось бы объяснять).
    """
    profile = _profile(db, user)
    profile.privacy = body.model_dump()
    db.commit()
    return profile.privacy


@router.get("/consents", response_model=list[ConsentOut], summary="Мои согласия (152-ФЗ)")
def get_consents(user: CurrentCandidate, db: DB):
    return list(current_consents(db, user.id).values())


@router.post("/consents", response_model=list[ConsentOut], responses=errors(400, 409), summary="Дать или отозвать согласие")
def change_consent(body: ConsentIn, user: CurrentCandidate, db: DB):
    """
    profile_publication — показ профиля работодателям: без него кандидат не
    попадает в поиск и подборки. Отзыв pd_processing означает отказ от
    обработки данных — используйте удаление учётной записи.
    """
    if body.kind == "pd_processing" and not body.granted:
        raise AppError("Для отзыва согласия на обработку данных удалите учётную запись", code="use_account_deletion")
    if body.kind == "profile_publication" and body.granted:
        minors.ensure_publication_allowed(db, user)
    set_consent(db, user.id, body.kind, body.granted)
    audit(db, user.id, "consent.changed", "user", user.id, kind=body.kind, granted=body.granted)
    db.commit()
    return list(current_consents(db, user.id).values())


@router.get("/consents/kinds", response_model=dict[str, str], summary="Виды согласий и их тексты")
def consent_kinds():
    return CONSENT_KINDS


# ------------------------------------------------------------------ опрос


@router.post("/survey", response_model=SurveyOut, status_code=201, responses=errors(400), summary="Пройти опрос по отрасли и специализации")
def submit_survey(body: SurveyIn, user: CurrentCandidate, db: DB):
    """
    Обязательный шаг перед тестом. Обновляет специализацию и стек профиля.
    Дата рождения обязательна, если её ещё нет в профиле
    (`birth_date_required`): от неё зависят правила для 14–17 лет.
    """
    profile = _profile(db, user)
    if body.birth_date is None and profile.birth_date is None:
        raise AppError("Укажите дату рождения: от возраста зависят правила для кандидатов 14–17 лет",
                       code="birth_date_required")
    data = body.model_dump(exclude={"birth_date"})
    survey = Survey(user_id=user.id, **data)
    db.add(survey)
    if body.birth_date is not None:
        profile.birth_date = body.birth_date
        minors.on_profile_changed(db, user, profile)
    if body.industry:
        profile.industry = body.industry
    profile.primary_specialization = body.specialization
    profile.primary_track = body.track
    if body.experience_years is not None:
        profile.experience_years = body.experience_years
    profile.stack = list(dict.fromkeys((profile.stack or []) + body.stack))
    profile.roles = list(dict.fromkeys((profile.roles or []) + body.roles))
    if body.work_formats:
        profile.work_formats = body.work_formats
    db.commit()
    return _survey_out(survey)


def _survey_out(s: Survey) -> SurveyOut:
    return SurveyOut(
        id=str(s.id),
        industry=s.industry,
        specialization=s.specialization,
        specialization_title=SPECIALIZATIONS.get(s.specialization, s.specialization),
        track=s.track,
        track_title=track_title(s.specialization, s.track),
        self_level=s.self_level,
        experience_years=s.experience_years,
        stack=s.stack or [],
        roles=s.roles or [],
        work_formats=s.work_formats or [],
        goals=s.goals,
        created_at=s.created_at,
    )


@router.get("/survey", response_model=SurveyHistoryOut, summary="История опросов")
def survey_history(user: CurrentCandidate, db: DB):
    rows = db.scalars(select(Survey).where(Survey.user_id == user.id).order_by(Survey.created_at.desc()))
    items = [_survey_out(s) for s in rows]
    return SurveyHistoryOut(latest=items[0] if items else None, history=items)


# ------------------------------------------------------------------ данные


@router.get("/data-export", response_model=DataExportOut, summary="Выгрузка всех моих данных")
def data_export(user: CurrentCandidate, db: DB):
    profile = _profile(db, user)
    audit(db, user.id, "data.exported", "user", user.id)
    db.commit()

    def rows(model, *conds):
        out = []
        for r in db.scalars(select(model).where(*conds)):
            row = {}
            for c in model.__table__.columns:
                if c.name in EXPORT_HIDDEN_COLUMNS:
                    continue
                value = getattr(r, c.name)
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                elif isinstance(value, uuid.UUID):
                    value = str(value)
                row[c.name] = value
            if model is Attempt and row.get("result"):
                row["result"] = {k: v for k, v in row["result"].items() if k in EXPORT_RESULT_FIELDS}
            out.append(row)
        return out

    received_kind = (select(Invitation.id).where(Invitation.candidate_user_id == user.id),
                     select(Application.id).where(Application.candidate_user_id == user.id))
    return DataExportOut(
        user={"id": str(user.id), "email": user.email, "public_id": user.public_id, "created_at": user.created_at.isoformat()},
        profile=_profile_out(db, user, profile).model_dump(mode="json"),
        surveys=rows(Survey, Survey.user_id == user.id),
        grades=rows(CandidateGrade, CandidateGrade.user_id == user.id),
        grade_history=rows(GradeHistory, GradeHistory.user_id == user.id),
        attempts=rows(Attempt, Attempt.user_id == user.id),
        invitations=rows(Invitation, Invitation.candidate_user_id == user.id),
        applications=rows(Application, Application.candidate_user_id == user.id),
        tasks=rows(TaskAssignment, TaskAssignment.candidate_user_id == user.id),
        fsp_link=rows(FspLink, FspLink.user_id == user.id),
        fsp_achievements=rows(FspAchievement, FspAchievement.user_id == user.id),
        consents=rows(Consent, Consent.user_id == user.id),
        # вся переписка кандидата: и его сообщения, и ответы компаний
        messages=rows(Message, Message.ref_id.in_(received_kind[0].union(received_kind[1]))),
        guardian_consent=rows(GuardianConsent, GuardianConsent.user_id == user.id),
    )


@router.delete("/account", status_code=204, responses=errors(403), summary="Удалить учётную запись")
def delete_account(user: CurrentCandidate, db: DB):
    """
    Персональные данные удаляются или обезличиваются, учётная запись
    отключается, сессии отзываются:

    * поля профиля, дата рождения, резюме, снимок ФСП, сообщения кандидата,
      согласие представителя;
    * копии писем на адреса кандидата и представителя в базе платформы;
    * цели из опросов, сопроводительные письма, тексты ответов на задания;
    * в подборках работодателей кандидат показывается как «недоступен».

    Попытки теста остаются псевдонимизированными (без профиля и контактов) —
    они нужны для статистики качества банка заданий. Демо-учётную запись
    удалить нельзя (`demo_account`).
    """
    if user.is_demo:
        raise Forbidden("Демо-учётную запись удалить нельзя: ею пользуются все посетители стенда", code="demo_account")
    profile = _profile(db, user)
    guardian = db.get(GuardianConsent, user.id)
    forget_recipient(db, user.email, profile.contact_email, guardian.guardian_email if guardian else None)
    for field in ("full_name", "phone", "telegram", "contact_email", "city", "about", "resume_filename", "resume_suggestions"):
        setattr(profile, field, None)
    profile.open_to_offers = False
    profile.birth_date = None
    profile.salary_expectation = None
    profile.stack, profile.roles, profile.soft_skills = [], [], []
    resume = get_settings().data_dir / "resumes" / ("%s.pdf" % user.id)
    if resume.exists():
        resume.unlink()
    db.query(FspAchievement).filter(FspAchievement.user_id == user.id).delete()
    db.query(Message).filter(Message.sender_user_id == user.id).delete()
    db.query(FspLink).filter(FspLink.user_id == user.id).delete()
    db.query(GuardianConsent).filter(GuardianConsent.user_id == user.id).delete()
    db.query(EmailToken).filter(EmailToken.user_id == user.id).delete()
    db.query(OidcState).filter(OidcState.user_id == user.id).delete()
    db.execute(update(Survey).where(Survey.user_id == user.id).values(goals=None))
    db.execute(update(Application).where(Application.candidate_user_id == user.id).values(cover_letter=None))
    db.execute(update(TaskAssignment).where(TaskAssignment.candidate_user_id == user.id).values(answer=None))
    set_consent(db, user.id, "profile_publication", False)
    set_consent(db, user.id, "pd_processing", False)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    user.email = "deleted-%s@deleted.local" % user.id.hex[:12]
    user.password_hash = None
    user.external_sub = None
    user.is_active = False
    audit(db, None, "account.deleted", "user", user.id)
    db.commit()
    return Response(status_code=204)


@router.get("/grades", response_model=list[GradeOut], summary="Мои категории")
def my_grades(user: CurrentCandidate, db: DB):
    grades = db.scalars(select(CandidateGrade).where(CandidateGrade.user_id == user.id))
    return [GradeOut(specialization=g.specialization, level=g.level, assigned_at=g.assigned_at, last_change_at=g.last_change_at)
            for g in grades]
