"""Кабинет кандидата: приглашения, вакансии и отклики, регулярные задания."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.errors import AppError, NotFound, errors
from app.models import Application, CandidateGrade, CandidateProfile, Company, Invitation, Need
from app.models.interactions import DECLINE_REASONS
from app.reference import SALARY_NOTE
from app.schemas import MessageIn, TextOut, ThreadMessageOut
from app.security.deps import DB, CurrentCandidate
from app.services import interactions, messages, minors, tasks, trust
from app.services.vacancies import vacancy_out

router = APIRouter(prefix="/api/v1/candidate", tags=["Кандидат: приглашения и отклики"], responses=errors(403))


class InvitationOut(BaseModel):
    id: str
    company: dict
    title: str
    description: str
    salary_from: int
    salary_to: int
    salary_note: str = Field(SALARY_NOTE, description="Основа сумм: до вычета НДФЛ")
    work_format: str | None
    contact_method: str
    suitable_for_minors: bool = False
    status: str
    created_at: datetime
    viewed_at: datetime | None
    responded_at: datetime | None
    expires_at: datetime
    decline_reason: str | None
    need: dict | None
    why_you: list[str] = Field(description="Почему работодатель выбрал кандидата (из обоснования подборки)")
    company_trust: dict = Field(description="Показатели компании: дней на платформе, приглашений, доля принятых, жалобы, предупреждения")
    contacts_shared: bool = Field(description="Компания сейчас видит контакты кандидата")
    unread_messages: int = Field(0, description="Непрочитанные сообщения от компании")
    contacts_revoked_at: datetime | None
    salary_warnings: list[str] = Field(description="Признаки неправдоподобной вилки (предупреждение, не запрет)")
    timeline: list[dict]


class AcceptIn(BaseModel):
    message: str | None = Field(None, max_length=1000, description="Сообщение работодателю")


class DeclineIn(BaseModel):
    reason: Literal["salary", "format", "stack", "not_looking", "company", "suspicious", "other"]
    comment: str | None = Field(None, max_length=1000)


class ApplyIn(BaseModel):
    need_id: uuid.UUID
    cover_letter: str | None = Field(None, max_length=3000)


class ApplicationOut(BaseModel):
    id: str
    vacancy: dict
    status: str
    cover_letter: str | None
    employer_comment: str | None
    contacts_shared: bool
    unread_messages: int = 0
    created_at: datetime
    updated_at: datetime
    timeline: list[dict]


class TaskAnswerIn(BaseModel):
    option: str | None = Field(None, max_length=1, description="Для заданий с выбором")
    number: float | str | None = Field(None, description="Для числовых заданий")
    text: str | None = Field(None, max_length=5000, description="Для заданий «предложите подход»")


class TaskInfo(BaseModel):
    title: str
    body: str
    kind: str = Field(description="choice | numeric | approach")
    options: list[dict]
    company: str
    level_range: list[str]


class AssignmentOut(BaseModel):
    id: str
    status: str = Field(description="assigned | submitted | reviewed | expired")
    assigned_at: datetime
    due_at: datetime
    submitted_at: datetime | None
    auto_correct: bool | None
    employer_score: int | None
    employer_comment: str | None
    answer: dict | None
    task: TaskInfo


class RecommendedOut(BaseModel):
    category: dict
    minor: bool
    items: list[dict] = Field(description="Вакансии; fits_my_category — совпадает с категорией кандидата, salary_fits — вилка не ниже ожиданий")


def _category_of(db, inv: Invitation) -> tuple[str | None, str | None]:
    """Категория для сравнения вилки с рынком: из потребности или из категории кандидата."""
    if inv.need_id:
        need = db.get(Need, inv.need_id)
        if need is not None:
            return need.specialization, need.level
    profile = db.get(CandidateProfile, inv.candidate_user_id)
    spec = profile.primary_specialization if profile else None
    grade = db.scalar(select(CandidateGrade).where(CandidateGrade.user_id == inv.candidate_user_id,
                                                   CandidateGrade.specialization == spec)) if spec else None
    return spec, grade.level if grade else None


def _invitation_out(db, inv: Invitation) -> InvitationOut:
    company = db.get(Company, inv.company_id)
    need = db.get(Need, inv.need_id) if inv.need_id else None
    why = (inv.match or {}).get("highlights", [])
    return InvitationOut(
        id=str(inv.id),
        company={"id": str(company.id), "name": company.name, "industry": company.industry, "city": company.city,
                 "website": company.website, "description": company.description},
        title=inv.title,
        description=inv.description,
        salary_from=inv.salary_from,
        salary_to=inv.salary_to,
        work_format=inv.work_format,
        contact_method=inv.contact_method,
        suitable_for_minors=bool(inv.suitable_for_minors),
        status=inv.status,
        created_at=inv.created_at,
        viewed_at=inv.viewed_at,
        responded_at=inv.responded_at,
        expires_at=inv.expires_at,
        decline_reason=inv.decline_reason,
        need=None if need is None else {"id": str(need.id), "title": need.title, "level": need.level},
        why_you=why,
        company_trust=trust.company_trust(db, company),
        contacts_shared=inv.status == "accepted" and inv.contacts_revoked_at is None,
        unread_messages=messages.unread(db, "invitation", inv.id, "candidate"),
        contacts_revoked_at=inv.contacts_revoked_at,
        salary_warnings=trust.salary_warnings(db, inv.salary_from, inv.salary_to, *_category_of(db, inv)),
        timeline=interactions.timeline(db, "invitation", inv.id),
    )


@router.get("/invitations", response_model=list[InvitationOut], summary="Входящие приглашения")
def list_invitations(user: CurrentCandidate, db: DB, status: str | None = Query(None)):
    """Кандидат видит только свои приглашения. Условия (вилка, компания, способ связи) видны сразу."""
    query = select(Invitation).where(Invitation.candidate_user_id == user.id).order_by(Invitation.created_at.desc())
    rows = list(db.scalars(query))
    for inv in rows:
        interactions.expire_if_needed(db, inv)
    db.commit()
    if status:
        rows = [r for r in rows if r.status == status]
    return [_invitation_out(db, inv) for inv in rows]


@router.get("/invitations/{invitation_id}", response_model=InvitationOut, responses=errors(404), summary="Приглашение (отмечается просмотренным)")
def get_invitation(invitation_id: uuid.UUID, user: CurrentCandidate, db: DB):
    inv = interactions.get_candidate_invitation(db, user, invitation_id)
    interactions.mark_viewed(db, inv)
    return _invitation_out(db, inv)


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationOut, responses=errors(404, 409), summary="Принять приглашение")
def accept(invitation_id: uuid.UUID, body: AcceptIn, user: CurrentCandidate, db: DB):
    """После принятия работодатель видит контакты кандидата."""
    inv = interactions.accept(db, user, invitation_id, body.message)
    return _invitation_out(db, inv)


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationOut, responses=errors(404, 409), summary="Отклонить приглашение")
def decline(invitation_id: uuid.UUID, body: DeclineIn, user: CurrentCandidate, db: DB):
    """Причина отказа уходит работодателю как обратная связь. «suspicious» — жалоба на недобросовестное предложение."""
    inv = interactions.decline(db, user, invitation_id, body.reason, body.comment)
    return _invitation_out(db, inv)


@router.post("/invitations/{invitation_id}/revoke-contacts", response_model=InvitationOut, responses=errors(404, 409), summary="Закрыть компании доступ к контактам")
def revoke_invitation_contacts(invitation_id: uuid.UUID, user: CurrentCandidate, db: DB):
    """После принятия приглашения кандидат может передумать: компания перестаёт видеть контакты на платформе."""
    return _invitation_out(db, interactions.revoke_contacts(db, user, "invitation", invitation_id))


@router.get("/invitations/{invitation_id}/messages", response_model=list[ThreadMessageOut], responses=errors(404), summary="Переписка по приглашению")
def invitation_messages(invitation_id: uuid.UUID, user: CurrentCandidate, db: DB):
    return messages.thread(db, "invitation", interactions.get_candidate_invitation(db, user, invitation_id), "candidate")


@router.post("/invitations/{invitation_id}/messages", response_model=ThreadMessageOut, status_code=201, responses=errors(404, 409, 429), summary="Написать компании по приглашению")
def post_invitation_message(invitation_id: uuid.UUID, body: MessageIn, user: CurrentCandidate, db: DB):
    """Вопросы до принятия приглашения: контакты при этом не раскрываются."""
    inv = interactions.get_candidate_invitation(db, user, invitation_id)
    return messages.post(db, "invitation", inv, "candidate", user, body.body)


@router.get("/applications/{application_id}/messages", response_model=list[ThreadMessageOut], responses=errors(404), summary="Переписка по отклику")
def application_messages(application_id: uuid.UUID, user: CurrentCandidate, db: DB):
    return messages.thread(db, "application", interactions.get_candidate_application(db, user, application_id), "candidate")


@router.post("/applications/{application_id}/messages", response_model=ThreadMessageOut, status_code=201, responses=errors(404, 409, 429), summary="Написать компании по отклику")
def post_application_message(application_id: uuid.UUID, body: MessageIn, user: CurrentCandidate, db: DB):
    app = interactions.get_candidate_application(db, user, application_id)
    return messages.post(db, "application", app, "candidate", user, body.body)


@router.get("/decline-reasons", response_model=dict[str, str], summary="Причины отказа")
def decline_reasons():
    return DECLINE_REASONS


class ComplaintIn(BaseModel):
    invitation_id: uuid.UUID | None = Field(None, description="Жалоба на приглашение…")
    vacancy_id: uuid.UUID | None = Field(None, description="…или на опубликованную вакансию")
    reason: Literal["suspicious", "fake_vacancy", "salary_mismatch", "spam", "payment_request", "other"]
    comment: str | None = Field(None, max_length=1000)


@router.get("/complaint-reasons", response_model=dict[str, str], summary="Причины жалобы на работодателя")
def complaint_reasons():
    return trust.COMPLAINT_REASONS


@router.post("/complaints", response_model=TextOut, status_code=201, responses=errors(400, 404, 409), summary="Пожаловаться на приглашение или вакансию")
def complain(body: ComplaintIn, user: CurrentCandidate, db: DB):
    """
    Жалобы видит модератор. Автоматическую проверку компании запускают
    только жалобы кандидатов, которые с ней взаимодействовали (получили
    приглашение или откликнулись), и считаются разные авторы — один человек
    не может приостановить компанию серией жалоб.
    """
    if (body.invitation_id is None) == (body.vacancy_id is None):
        raise AppError("Укажите либо приглашение, либо вакансию", code="complaint_target_required")
    if body.invitation_id:
        inv = interactions.get_candidate_invitation(db, user, body.invitation_id)
        company = db.get(Company, inv.company_id)
        trust.add_complaint(db, company, user, body.reason, body.comment, invitation_id=inv.id)
    else:
        need = db.get(Need, body.vacancy_id)
        if need is None or not need.is_published:
            raise NotFound("Вакансия не найдена")
        company = db.get(Company, need.company_id)
        trust.add_complaint(db, company, user, body.reason, body.comment, need_id=need.id)
    db.commit()
    return {"message": "Жалоба отправлена модератору. Спасибо — это помогает защищать кандидатов."}


# ------------------------------------------------------------------ отклики


def _application_out(db, app: Application) -> ApplicationOut:
    need = db.get(Need, app.need_id)
    company = db.get(Company, app.company_id)
    return ApplicationOut(
        id=str(app.id),
        vacancy=vacancy_out(need, company),
        status=app.status,
        cover_letter=app.cover_letter,
        employer_comment=app.employer_comment,
        contacts_shared=app.status != "withdrawn" and app.contacts_revoked_at is None,
        unread_messages=messages.unread(db, "application", app.id, "candidate"),
        created_at=app.created_at,
        updated_at=app.updated_at,
        timeline=interactions.timeline(db, "application", app.id),
    )


@router.get("/vacancies/recommended", response_model=RecommendedOut, summary="Вакансии под мою категорию")
def recommended_vacancies(user: CurrentCandidate, db: DB, limit: int = Query(20, ge=1, le=100)):
    profile = db.get(CandidateProfile, user.id)
    grades = {g.specialization: g.level for g in db.scalars(select(CandidateGrade).where(CandidateGrade.user_id == user.id))}
    spec = profile.primary_specialization if profile else None
    query = (
        select(Need, Company)
        .join(Company, Company.id == Need.company_id)
        .where(Need.is_published.is_(True), Need.status == "open", Company.review_status == "active")
    )
    if spec:
        query = query.where(Need.specialization == spec)
    minor = minors.is_minor(profile)
    if minor:
        query = query.where(Need.suitable_for_minors.is_(True))
    rows = db.execute(query.order_by(Need.published_at.desc())).all()
    level = grades.get(spec) if spec else None
    items = []
    for need, company in rows:
        out = vacancy_out(need, company)
        out["fits_my_category"] = level == need.level
        if profile and profile.salary_expectation:
            out["salary_fits"] = profile.salary_expectation <= need.salary_to
        items.append(out)
    items.sort(key=lambda v: not v["fits_my_category"])  # внутри групп — от новых к старым, как в запросе
    return {"category": {"specialization": spec, "level": level}, "minor": minor, "items": items[:limit]}


@router.post("/applications", response_model=ApplicationOut, status_code=201, responses=errors(404, 409), summary="Откликнуться на вакансию")
def apply(body: ApplyIn, user: CurrentCandidate, db: DB):
    """Отклик открывает работодателю контакты кандидата."""
    app = interactions.apply(db, user, body.need_id, body.cover_letter)
    return _application_out(db, app)


@router.get("/applications", response_model=list[ApplicationOut], summary="Мои отклики и их статусы")
def list_applications(user: CurrentCandidate, db: DB):
    rows = db.scalars(select(Application).where(Application.candidate_user_id == user.id).order_by(Application.created_at.desc()))
    return [_application_out(db, a) for a in rows]


@router.post("/applications/{application_id}/revoke-contacts", response_model=ApplicationOut, responses=errors(404), summary="Закрыть компании доступ к контактам")
def revoke_application_contacts(application_id: uuid.UUID, user: CurrentCandidate, db: DB):
    return _application_out(db, interactions.revoke_contacts(db, user, "application", application_id))


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationOut, responses=errors(404, 409), summary="Отозвать отклик")
def withdraw_application(application_id: uuid.UUID, user: CurrentCandidate, db: DB):
    app = interactions.withdraw_application(db, user, application_id)
    return _application_out(db, app)


# ------------------------------------------------------------------ задания


def _assignment_out(assignment, task, company) -> dict:
    return {
        "id": str(assignment.id),
        "status": assignment.status,
        "assigned_at": assignment.assigned_at,
        "due_at": assignment.due_at,
        "submitted_at": assignment.submitted_at,
        "auto_correct": assignment.auto_correct,
        "employer_score": assignment.employer_score,
        "employer_comment": assignment.employer_comment,
        "answer": assignment.answer,
        "task": {
            "title": task.title,
            "body": task.body,
            "kind": task.kind,
            "options": task.options,
            "company": company.name,
            "level_range": [task.level_min, task.level_max],
        },
    }


@router.get("/tasks", response_model=list[AssignmentOut], summary="Регулярные задания от работодателей")
def list_tasks(user: CurrentCandidate, db: DB):
    """При открытии раздела выдаётся новое задание, если подошёл срок и есть подходящие."""
    return [_assignment_out(a, t, c) for a, t, c in tasks.candidate_assignments(db, user)]


@router.post("/tasks/{assignment_id}/submit", response_model=AssignmentOut, responses=errors(400, 404, 409), summary="Отправить решение задания")
def submit_task(assignment_id: uuid.UUID, body: TaskAnswerIn, user: CurrentCandidate, db: DB):
    assignment = tasks.submit(db, user, assignment_id, body.model_dump(exclude_none=True))
    rows = tasks.candidate_assignments(db, user)
    match = next(r for r in rows if r[0].id == assignment.id)
    return _assignment_out(*match)
