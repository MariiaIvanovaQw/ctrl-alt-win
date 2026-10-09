"""
Регулярные короткие задания от работодателей.

Выдача без отдельного планировщика: платформа проверяет, не пора ли
предложить задание, когда кандидат входит, открывает кабинет или раздел
заданий («система периодически предлагает» из ТЗ). Новое задание
выдаётся, если с прошлой выдачи прошло task_assign_interval_days дней и
открытых заданий нет; кандидату уходит письмо.

Какое задание выдать: активное, подходящее категории кандидата, которое
он ещё не получал, от компании без ограничений модератора. Из подходящих
берётся задание, которое выдавалось реже всего, — иначе задания первого
работодателя доставались бы всем, а задания новых не доходили бы ни до кого.

Работодатель может и адресно предложить задание конкретному кандидату
(уточнение постановщиков: «может предложить вакансию и тест точечно»).

Задания с выбором ответа и числом проверяются автоматически, задания
«предложите подход» оценивает работодатель по шкале 1–5. Результаты
поддерживают свежесть профиля и дают работодателю сигнал о кандидате.
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, NotFound, TooManyRequests
from app.models import CandidateGrade, CandidateProfile, Company, EmployerTask, Need, TaskAssignment, User
from app.reference import LEVEL_INDEX
from app.services import integrity, trust, webhooks
from app.services.consents import has_consent
from app.services.mailer import send_email

TARGETED_PER_COMPANY_PER_DAY = 50


def create_task(db: Session, company: Company, data: dict) -> EmployerTask:
    kind = data["kind"]
    if kind == "choice":
        options = data.get("options") or []
        ids = [o["id"] for o in options]
        if len(options) < 2 or len(set(ids)) != len(ids) or data.get("correct_option") not in ids:
            raise AppError("Для задания с выбором нужны разные варианты и верный вариант среди них", code="invalid_task")
        answer = {"correct_option": data["correct_option"]}
    elif kind == "numeric":
        if data.get("correct_number") is None:
            raise AppError("Для числового задания нужен верный ответ", code="invalid_task")
        answer = {"correct_number": float(data["correct_number"]), "tolerance": float(data.get("tolerance") or 0)}
        options = []
    else:
        answer, options = None, []
    if LEVEL_INDEX[data["level_min"]] > LEVEL_INDEX[data["level_max"]]:
        raise AppError("Минимальный уровень выше максимального", code="invalid_task")
    if data.get("need_id"):
        need = db.get(Need, data["need_id"])
        if need is None or need.company_id != company.id:
            raise NotFound("Потребность не найдена")
    task = EmployerTask(
        company_id=company.id,
        need_id=data.get("need_id"),
        specialization=data["specialization"],
        level_min=data["level_min"],
        level_max=data["level_max"],
        title=data["title"],
        body=data["body"],
        kind=kind,
        options=options,
        answer=answer,
    )
    db.add(task)
    db.commit()
    return task


def _expire(db: Session, assignment: TaskAssignment) -> None:
    if assignment.status == "assigned" and assignment.due_at < utcnow():
        assignment.status = "expired"


def _notify(db: Session, user: User, task: EmployerTask, company: Company, due_days: int) -> None:
    profile = db.get(CandidateProfile, user.id)
    to = (profile.contact_email if profile and profile.contact_email else None) or user.email
    send_email(
        db, to, "Новое задание от %s: %s" % (company.name, task.title),
        "Компания %s предлагает короткое задание «%s». Решите его или предложите подход в личном кабинете "
        "(раздел «Задания») в течение %d дней: свежие результаты поднимают профиль в подборках." % (company.name, task.title, due_days),
    )


def assign_if_due(db: Session, user: User) -> TaskAssignment | None:
    settings = get_settings()
    profile = db.get(CandidateProfile, user.id)
    spec = profile.primary_specialization if profile else None
    if not spec:
        return None
    grade = db.scalar(select(CandidateGrade).where(CandidateGrade.user_id == user.id, CandidateGrade.specialization == spec))
    if grade is None:
        return None
    assignments = list(
        db.scalars(select(TaskAssignment).where(TaskAssignment.candidate_user_id == user.id).order_by(TaskAssignment.assigned_at.desc()))
    )
    for a in assignments:
        _expire(db, a)
    if any(a.status == "assigned" for a in assignments):
        return None
    if assignments and utcnow() - assignments[0].assigned_at < timedelta(days=settings.task_assign_interval_days):
        return None
    received = {a.task_id for a in assignments}
    level = LEVEL_INDEX[grade.level]
    # сколько раз каждое задание уже выдавалось: выдаём самое «невыданное»
    issued = dict(db.execute(select(TaskAssignment.task_id, func.count()).group_by(TaskAssignment.task_id)).all())
    candidates = [
        (t, c)
        for t, c in db.execute(
            select(EmployerTask, Company)
            .join(Company, Company.id == EmployerTask.company_id)
            .where(EmployerTask.active.is_(True), EmployerTask.specialization == spec, Company.review_status == "active")
            .order_by(EmployerTask.created_at)
        ).all()
        if t.id not in received and LEVEL_INDEX[t.level_min] <= level <= LEVEL_INDEX[t.level_max]
    ]
    if not candidates:
        return None
    task, company = min(candidates, key=lambda tc: issued.get(tc[0].id, 0))
    assignment = TaskAssignment(
        task_id=task.id,
        candidate_user_id=user.id,
        due_at=utcnow() + timedelta(days=settings.task_due_days),
    )
    try:
        # Два одновременных запроса кандидата (вкладки, воркеры) выбирают одно и
        # то же задание: уникальный индекс пропустит одну выдачу. Точка сохранения
        # откатывает только её — работа вызывающего (токены при входе) остаётся.
        with db.begin_nested():
            db.add(assignment)
            _notify(db, user, task, company, settings.task_due_days)
    except IntegrityError:
        return None
    return assignment


def offer_due_task(db: Session, user: User) -> TaskAssignment | None:
    """Проверка «не пора ли предложить задание» при входе и открытии кабинета (без коммита)."""
    if user.role != "candidate":
        return None
    return assign_if_due(db, user)


def assign_to_candidate(db: Session, company: Company, task_id: uuid.UUID, candidate: User) -> TaskAssignment:
    """Адресное задание конкретному кандидату (например, после приглашения)."""
    trust.ensure_active(company)
    task = db.get(EmployerTask, task_id)
    if task is None or task.company_id != company.id:
        raise NotFound("Задание не найдено")
    if not task.active:
        raise Conflict("Задание отключено", code="task_inactive")
    if not has_consent(db, candidate.id, "profile_publication"):
        raise NotFound("Кандидат не найден")
    exists = db.scalar(select(TaskAssignment.id).where(TaskAssignment.task_id == task.id,
                                                       TaskAssignment.candidate_user_id == candidate.id))
    if exists:
        raise Conflict("Кандидат уже получал это задание", code="task_already_assigned")
    since = utcnow() - timedelta(days=1)
    sent_today = db.scalar(
        select(func.count()).select_from(TaskAssignment).join(EmployerTask, EmployerTask.id == TaskAssignment.task_id)
        .where(EmployerTask.company_id == company.id, TaskAssignment.assigned_at >= since)
    ) or 0
    if sent_today >= TARGETED_PER_COMPANY_PER_DAY:
        raise TooManyRequests("Превышен дневной лимит заданий компании", code="task_limit")
    settings = get_settings()
    assignment = TaskAssignment(task_id=task.id, candidate_user_id=candidate.id,
                                due_at=utcnow() + timedelta(days=settings.task_due_days))
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError as exc:  # два одновременных «Предложить задание»: уникальный индекс пропустит одно
        db.rollback()
        raise Conflict("Кандидат уже получал это задание", code="task_already_assigned") from exc
    _notify(db, candidate, task, company, settings.task_due_days)
    db.commit()
    return assignment


def candidate_assignments(db: Session, user: User) -> list[tuple[TaskAssignment, EmployerTask, Company]]:
    assign_if_due(db, user)
    db.commit()
    rows = db.execute(
        select(TaskAssignment, EmployerTask, Company)
        .join(EmployerTask, EmployerTask.id == TaskAssignment.task_id)
        .join(Company, Company.id == EmployerTask.company_id)
        .where(TaskAssignment.candidate_user_id == user.id)
        .order_by(TaskAssignment.assigned_at.desc())
    ).all()
    for a, _t, _c in rows:
        _expire(db, a)
    db.commit()
    return rows


def submit(db: Session, user: User, assignment_id: uuid.UUID, answer: dict) -> TaskAssignment:
    assignment = db.get(TaskAssignment, assignment_id)
    if assignment is None or assignment.candidate_user_id != user.id:
        raise NotFound("Задание не найдено")
    _expire(db, assignment)
    if assignment.status != "assigned":
        db.commit()
        raise Conflict("Задание уже закрыто", code="task_closed")
    task = db.get(EmployerTask, assignment.task_id)
    now = utcnow()
    if task.kind == "choice":
        choice = answer.get("option")
        if choice not in {o["id"] for o in task.options}:
            raise AppError("Выберите один из вариантов", code="invalid_answer")
        assignment.auto_correct = choice == task.answer["correct_option"]
        assignment.status = "reviewed"
        assignment.reviewed_at = now
    elif task.kind == "numeric":
        try:
            value = float(str(answer.get("number")).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise AppError("Ответ должен быть числом", code="invalid_answer") from exc
        assignment.auto_correct = abs(value - task.answer["correct_number"]) <= task.answer.get("tolerance", 0) + 1e-9
        assignment.status = "reviewed"
        assignment.reviewed_at = now
    else:
        text = (answer.get("text") or "").strip()
        if len(text) < 20:
            raise AppError("Опишите подход подробнее (не короче 20 символов)", code="invalid_answer")
        assignment.status = "submitted"
    assignment.answer = answer
    assignment.submitted_at = now
    if task.kind == "approach":
        integrity.check_approach_answer(db, assignment, task)
    profile = db.get(CandidateProfile, user.id)
    if profile is not None:
        profile.last_active_at = now
    webhooks.emit(db, task.company_id, "task.submitted", {
        "task": {"id": str(task.id), "title": task.title, "kind": task.kind},
        "assignment_id": str(assignment.id),
        "candidate_id": user.public_id,
        "auto_correct": assignment.auto_correct,
        "answer": answer,
    })
    db.commit()
    return assignment


def review(db: Session, company: Company, assignment_id: uuid.UUID, score: int, comment: str | None) -> TaskAssignment:
    assignment = db.get(TaskAssignment, assignment_id)
    task = db.get(EmployerTask, assignment.task_id) if assignment else None
    if assignment is None or task is None or task.company_id != company.id:
        raise NotFound("Решение не найдено")
    if task.kind != "approach":
        raise Conflict("Это задание проверяется автоматически", code="auto_checked")
    if assignment.status != "submitted":
        raise Conflict("Решение ещё не отправлено или уже оценено", code="not_reviewable")
    assignment.employer_score = score
    assignment.employer_comment = comment
    assignment.status = "reviewed"
    assignment.reviewed_at = utcnow()
    db.commit()
    return assignment
