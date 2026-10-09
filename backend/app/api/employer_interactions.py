"""Кабинет работодателя: приглашения, отклики и регулярные задания."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.employer import company_of, data_company
from app.errors import NotFound, errors
from app.models import Application, CandidateProfile, EmployerTask, Invitation, Need, TaskAssignment, User
from app.models.interactions import DECLINE_REASONS
from app.reference import SALARY_NOTE
from app.schemas import Level, MessageIn, SalaryRange, Specialization, ThreadMessageOut
from app.security.deps import DB, CurrentEmployer
from app.services import interactions, matching, messages, tasks
from app.services.cards import build_card, contacts_access, display_name, log_contact_view
from app.services.vacancies import vacancy_out

router = APIRouter(prefix="/api/v1/employer", tags=["Работодатель: выход на контакт"], responses=errors(403))


class InvitationIn(SalaryRange):
    candidate_id: str = Field(description="Псевдоним кандидата из подборки или поиска")
    need_id: uuid.UUID | None = Field(None, description="Привязка к потребности необязательна")
    selection_id: uuid.UUID | None = Field(None, description="Подборка, из которой пришёл кандидат (для обоснования)")
    title: str = Field(min_length=3, max_length=200, description="Должность или суть предложения")
    description: str = Field(min_length=20, max_length=5000, description="Описание предложения")
    work_format: Literal["office", "hybrid", "remote"] | None = None
    contact_method: str = Field(min_length=3, max_length=255, description="Как связаться: e-mail, телефон, Telegram рекрутера")
    suitable_for_minors: bool = Field(False, description="Подходит для несовершеннолетних кандидатов (15–17 лет): лёгкий труд, сокращённое рабочее время, без вредных и опасных условий (ст. 63, 92, 265 ТК РФ). Обязательно для кандидатов младше 18 лет")


class InvitationOut(BaseModel):
    id: str
    candidate_id: str
    candidate_name: str
    title: str
    description: str
    salary_from: int
    salary_to: int
    salary_note: str = SALARY_NOTE
    work_format: str | None
    contact_method: str
    suitable_for_minors: bool = False
    status: str
    decline_reason: str | None
    decline_reason_title: str | None
    decline_comment: str | None
    created_at: datetime
    viewed_at: datetime | None
    responded_at: datetime | None
    expires_at: datetime
    need_id: str | None
    match: dict | None
    contacts_visible: bool
    unread_messages: int = 0
    timeline: list[dict]


class RespondIn(BaseModel):
    status: Literal["invited", "rejected"]
    comment: str | None = Field(None, max_length=2000)


class TaskOption(BaseModel):
    id: str = Field(pattern="^[A-F]$", description="Буква варианта A–F")
    text: str = Field(min_length=1, max_length=500)


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=5000)
    kind: Literal["choice", "numeric", "approach"]
    specialization: Specialization
    level_min: Level = "junior"
    level_max: Level = "senior"
    need_id: uuid.UUID | None = Field(None, description="Своя потребность, к которой относится задание")
    options: list[TaskOption] | None = Field(None, min_length=2, max_length=6, description='Для choice: [{"id": "A", "text": "…"}, …]')
    correct_option: str | None = Field(None, pattern="^[A-F]$")
    correct_number: float | None = None
    tolerance: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "choice" and (not self.options or not self.correct_option):
            raise ValueError("для задания с выбором нужны options и correct_option")
        if self.kind == "numeric" and self.correct_number is None:
            raise ValueError("для числового задания нужен correct_number")
        return self


class ReviewIn(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)


class AssignTaskIn(BaseModel):
    candidate_id: str = Field(max_length=12, description="Псевдоним кандидата (public_id)")


class TaskCreatedOut(BaseModel):
    id: str
    title: str
    kind: str


class TaskSummaryOut(TaskCreatedOut):
    specialization: str
    level_range: list[str]
    active: bool
    assigned: int
    submitted: int
    awaiting_review: int


class SubmissionOut(BaseModel):
    assignment_id: str
    candidate_id: str
    candidate_name: str
    status: str
    answer: dict | None
    submitted_at: datetime | None
    auto_correct: bool | None
    employer_score: int | None
    employer_comment: str | None
    similar_to: dict | None = Field(None, description="Антиплагиат: самый похожий ответ другого кандидата {candidate_id, share}")


class SubmissionsOut(BaseModel):
    task: TaskCreatedOut
    submissions: list[SubmissionOut]


class ReviewOut(BaseModel):
    assignment_id: str
    status: str
    employer_score: int | None


class AssignmentOut(BaseModel):
    assignment_id: str
    candidate_id: str
    status: str
    due_at: datetime


class DeclineReasonStat(BaseModel):
    reason: str
    title: str
    count: int


class InvitationStatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    acceptance_rate: float | None
    decline_reasons: list[DeclineReasonStat]


class ApplicationOut(BaseModel):
    id: str
    vacancy: dict
    candidate_id: str
    status: str
    cover_letter: str | None
    employer_comment: str | None
    created_at: datetime
    updated_at: datetime
    timeline: list[dict]
    unread_messages: int
    candidate: dict | None = Field(description="Карточка кандидата (контакты — если кандидат откликнулся и не закрыл доступ)")
    match: dict | None = Field(None, description="Соответствие кандидата вакансии")


def _invitation_out(db, inv: Invitation) -> InvitationOut:
    candidate = db.get(User, inv.candidate_user_id)
    profile = db.get(CandidateProfile, candidate.id)
    return InvitationOut(
        id=str(inv.id),
        candidate_id=candidate.public_id,
        candidate_name=display_name(candidate, profile) if profile else candidate.public_id,
        title=inv.title,
        description=inv.description,
        salary_from=inv.salary_from,
        salary_to=inv.salary_to,
        work_format=inv.work_format,
        contact_method=inv.contact_method,
        suitable_for_minors=bool(inv.suitable_for_minors),
        status=inv.status,
        decline_reason=inv.decline_reason,
        decline_reason_title=DECLINE_REASONS.get(inv.decline_reason) if inv.decline_reason else None,
        decline_comment=inv.decline_comment,
        created_at=inv.created_at,
        viewed_at=inv.viewed_at,
        responded_at=inv.responded_at,
        expires_at=inv.expires_at,
        need_id=str(inv.need_id) if inv.need_id else None,
        match=matching.sanitize_match(inv.match, profile) if profile else inv.match,
        contacts_visible=inv.status == "accepted" and inv.contacts_revoked_at is None,
        unread_messages=messages.unread(db, "invitation", inv.id, "employer"),
        timeline=interactions.timeline(db, "invitation", inv.id),
    )


@router.post("/invitations", response_model=InvitationOut, status_code=201, responses=errors(400, 404, 409, 429),
             summary="Пригласить кандидата")
def invite(body: InvitationIn, user: CurrentEmployer, db: DB):
    """
    Основной сценарий платформы: работодатель сам выходит на кандидата.
    Вилка зарплаты, описание и способ связи обязательны. Повторное
    приглашение тому же кандидату, пока предыдущее действует, — 409.
    """
    company = company_of(db, user)
    inv = interactions.send_invitation(db, company, body.candidate_id, body.model_dump())
    return _invitation_out(db, inv)


@router.get("/invitations", response_model=list[InvitationOut], summary="Отправленные приглашения и их статусы")
def list_invitations(user: CurrentEmployer, db: DB, status: str | None = Query(None), need_id: uuid.UUID | None = None):
    company = company_of(db, user)
    query = select(Invitation).where(Invitation.company_id == company.id)
    if need_id:
        query = query.where(Invitation.need_id == need_id)
    rows = list(db.scalars(query.order_by(Invitation.created_at.desc())))
    for inv in rows:
        interactions.expire_if_needed(db, inv)
    db.commit()
    if status:
        rows = [r for r in rows if r.status == status]
    return [_invitation_out(db, r) for r in rows]


@router.get("/invitations/{invitation_id}", response_model=InvitationOut, responses=errors(404), summary="Приглашение")
def get_invitation(invitation_id: uuid.UUID, user: CurrentEmployer, db: DB):
    inv = interactions.get_company_invitation(db, company_of(db, user), invitation_id)
    db.commit()
    return _invitation_out(db, inv)


@router.post("/invitations/{invitation_id}/withdraw", response_model=InvitationOut, responses=errors(404, 409),
             summary="Отозвать приглашение")
def withdraw(invitation_id: uuid.UUID, user: CurrentEmployer, db: DB):
    inv = interactions.withdraw(db, company_of(db, user), invitation_id)
    return _invitation_out(db, inv)


@router.get("/invitations/{invitation_id}/messages", response_model=list[ThreadMessageOut], responses=errors(404),
            summary="Переписка по приглашению")
def invitation_messages(invitation_id: uuid.UUID, user: CurrentEmployer, db: DB):
    inv = interactions.get_company_invitation(db, company_of(db, user), invitation_id)
    return messages.thread(db, "invitation", inv, "employer")


@router.post("/invitations/{invitation_id}/messages", response_model=ThreadMessageOut, status_code=201,
             responses=errors(404, 409, 429), summary="Написать кандидату по приглашению")
def post_invitation_message(invitation_id: uuid.UUID, body: MessageIn, user: CurrentEmployer, db: DB):
    inv = interactions.get_company_invitation(db, company_of(db, user), invitation_id)
    return messages.post(db, "invitation", inv, "employer", user, body.body)


@router.get("/applications/{application_id}/messages", response_model=list[ThreadMessageOut], responses=errors(404),
            summary="Переписка по отклику")
def application_messages(application_id: uuid.UUID, user: CurrentEmployer, db: DB):
    app = interactions.get_company_application(db, company_of(db, user), application_id)
    return messages.thread(db, "application", app, "employer")


@router.post("/applications/{application_id}/messages", response_model=ThreadMessageOut, status_code=201,
             responses=errors(404, 409, 429), summary="Написать кандидату по отклику")
def post_application_message(application_id: uuid.UUID, body: MessageIn, user: CurrentEmployer, db: DB):
    app = interactions.get_company_application(db, company_of(db, user), application_id)
    return messages.post(db, "application", app, "employer", user, body.body)


@router.get("/invitations-stats", response_model=InvitationStatsOut, summary="Воронка приглашений")
def invitation_stats(user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    rows = list(db.scalars(select(Invitation).where(Invitation.company_id == company.id)))
    counts = {}
    reasons = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.decline_reason:
            reasons[r.decline_reason] = reasons.get(r.decline_reason, 0) + 1
    responded = counts.get("accepted", 0) + counts.get("declined", 0)
    return {
        "total": len(rows),
        "by_status": counts,
        "acceptance_rate": round(counts.get("accepted", 0) / responded, 3) if responded else None,
        "decline_reasons": [
            {"reason": k, "title": DECLINE_REASONS[k], "count": n} for k, n in sorted(reasons.items(), key=lambda x: -x[1])
        ],
    }


# ------------------------------------------------------------------ отклики


def _application_out(db, company, app: Application, with_card: bool) -> dict:
    """Карточка кандидата в отклике — по текущим правам: контакты, пока кандидат не закрыл доступ."""
    need = db.get(Need, app.need_id)
    candidate = db.get(User, app.candidate_user_id)
    out = {
        "id": str(app.id),
        "vacancy": vacancy_out(need, company),
        "candidate_id": candidate.public_id,
        "status": app.status,
        "cover_letter": app.cover_letter,
        "employer_comment": app.employer_comment,
        "created_at": app.created_at,
        "updated_at": app.updated_at,
        "timeline": interactions.timeline(db, "application", app.id),
        "unread_messages": messages.unread(db, "application", app.id, "employer"),
        "candidate": None,
    }
    facts = matching.load_facts(db, user_ids=[candidate.id], only_published=False)
    reason = contacts_access(db, company.id, candidate.id)
    if facts:
        same = [f for f in facts if f.grade.specialization == need.specialization] or facts
        out["candidate"] = build_card(same[0], contacts_reason=reason, full=with_card)
        out["match"] = matching.score_for_need(same[0], need, need.profile) if need.profile else None
    else:
        profile = db.get(CandidateProfile, candidate.id)
        out["candidate"] = {
            "candidate_id": candidate.public_id,
            "display_name": display_name(candidate, profile),
            "category": None,
            "note": "Кандидат ещё не прошёл тестирование",
            "contacts": {"email": profile.contact_email or candidate.email, "phone": profile.phone, "telegram": profile.telegram}
            if reason
            else None,
        }
    return out


@router.get("/applications", response_model=list[ApplicationOut], summary="Отклики на мои вакансии")
def list_applications(user: CurrentEmployer, db: DB, need_id: uuid.UUID | None = None, status: str | None = None):
    company = data_company(db, user)
    query = select(Application).where(Application.company_id == company.id)
    if need_id:
        query = query.where(Application.need_id == need_id)
    if status:
        query = query.where(Application.status == status)
    return [_application_out(db, company, a, with_card=False) for a in db.scalars(query.order_by(Application.created_at.desc()))]


@router.get("/applications/{application_id}", response_model=ApplicationOut, responses=errors(404),
            summary="Отклик (отмечается просмотренным)")
def get_application(application_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = data_company(db, user)
    app = interactions.get_company_application(db, company, application_id)
    interactions.employer_mark_viewed(db, app)
    if contacts_access(db, company.id, app.candidate_user_id):
        log_contact_view(db, user.id, app.candidate_user_id, "candidate_applied")
    db.commit()
    return _application_out(db, company, app, with_card=True)


@router.post("/applications/{application_id}/respond", response_model=ApplicationOut, responses=errors(404, 409),
             summary="Ответить на отклик")
def respond(application_id: uuid.UUID, body: RespondIn, user: CurrentEmployer, db: DB):
    company = data_company(db, user)
    app = interactions.employer_respond(db, company, application_id, body.status, body.comment)
    return _application_out(db, company, app, with_card=False)


# ------------------------------------------------------------------ задания


@router.post("/tasks", response_model=TaskCreatedOut, status_code=201, responses=errors(400, 404),
             summary="Создать регулярное задание")
def create_task(body: TaskIn, user: CurrentEmployer, db: DB):
    """
    Короткая задача для кандидатов категории: с выбором ответа, числом
    или открытая «предложите подход». Платформа сама выдаёт её кандидатам
    категории, а адресно — методом `POST /tasks/{id}/assign`.
    """
    task = tasks.create_task(db, company_of(db, user), body.model_dump())
    return TaskCreatedOut(id=str(task.id), title=task.title, kind=task.kind)


@router.post("/tasks/{task_id}/assign", response_model=AssignmentOut, status_code=201, responses=errors(404, 409, 429),
             summary="Предложить задание конкретному кандидату")
def assign_task(task_id: uuid.UUID, body: AssignTaskIn, user: CurrentEmployer, db: DB):
    """
    Адресное задание: кандидат получает его сразу (и письмо), без ожидания
    плановой выдачи. Например, после приглашения — проверить подход к
    задаче команды. Одно задание одному кандидату — один раз.
    """
    company = data_company(db, user)
    candidate = interactions.find_candidate(db, body.candidate_id)
    a = tasks.assign_to_candidate(db, company, task_id, candidate)
    return AssignmentOut(assignment_id=str(a.id), candidate_id=candidate.public_id, status=a.status, due_at=a.due_at)


@router.get("/tasks", response_model=list[TaskSummaryOut], summary="Мои задания")
def list_tasks(user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    out = []
    for t in db.scalars(select(EmployerTask).where(EmployerTask.company_id == company.id).order_by(EmployerTask.created_at.desc())):
        assignments = list(db.scalars(select(TaskAssignment).where(TaskAssignment.task_id == t.id)))
        out.append(
            {
                "id": str(t.id), "title": t.title, "kind": t.kind, "specialization": t.specialization,
                "level_range": [t.level_min, t.level_max], "active": t.active,
                "assigned": len(assignments),
                "submitted": sum(1 for a in assignments if a.status in ("submitted", "reviewed")),
                "awaiting_review": sum(1 for a in assignments if a.status == "submitted"),
            }
        )
    return out


@router.get("/tasks/{task_id}/submissions", response_model=SubmissionsOut, responses=errors(404), summary="Решения кандидатов")
def submissions(task_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    task = db.get(EmployerTask, task_id)
    if task is None or task.company_id != company.id:
        raise NotFound("Задание не найдено")
    out = []
    for a in db.scalars(select(TaskAssignment).where(TaskAssignment.task_id == task.id).order_by(TaskAssignment.assigned_at.desc())):
        candidate = db.get(User, a.candidate_user_id)
        profile = db.get(CandidateProfile, candidate.id)
        out.append(
            {
                "assignment_id": str(a.id), "candidate_id": candidate.public_id,
                "candidate_name": display_name(candidate, profile) if profile else candidate.public_id,
                "status": a.status, "answer": a.answer, "submitted_at": a.submitted_at, "auto_correct": a.auto_correct,
                "employer_score": a.employer_score, "employer_comment": a.employer_comment,
                # антиплагиат: самый похожий ответ другого кандидата на это задание
                "similar_to": a.similarity,
            }
        )
    return {"task": {"id": str(task.id), "title": task.title, "kind": task.kind}, "submissions": out}


@router.post("/tasks/submissions/{assignment_id}/review", response_model=ReviewOut, responses=errors(404, 409),
             summary="Оценить решение «предложите подход»")
def review(assignment_id: uuid.UUID, body: ReviewIn, user: CurrentEmployer, db: DB):
    a = tasks.review(db, company_of(db, user), assignment_id, body.score, body.comment)
    return {"assignment_id": str(a.id), "status": a.status, "employer_score": a.employer_score}
