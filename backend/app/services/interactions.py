"""
Выход на контакт: приглашения работодателя и отклики кандидата.

Приглашение — основной сценарий платформы: работодатель находит кандидата
в категории и сам предлагает работу с вилкой зарплаты. Кандидат видит
условия до начала общения, принимает или отклоняет с причиной; причина
отказа возвращается работодателю как обратная связь. Контакты кандидата
открываются только после принятия.

Статусы приглашения: sent → viewed → accepted | declined; работодатель
может отозвать (withdrawn), без ответа приглашение истекает (expired).
Статусы отклика: sent → viewed → invited | rejected; кандидат может
отозвать (withdrawn).

Изменения статусов уходят в ATS работодателя вебхуками (services/webhooks.py);
компания на проверке после жалоб не может приглашать (services/trust.py).
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, NotFound, TooManyRequests
from app.models import Application, CandidateProfile, Company, InteractionEvent, Invitation, Need, Selection, User
from app.models.interactions import DECLINE_REASONS
from app.services import matching, minors, trust, webhooks
from app.services.consents import audit, has_consent
from app.services.export import candidate_json_resume
from app.services.mailer import send_email
from app.services.search import need_profile

ACTIVE_INVITATION = ("sent", "viewed")


def rub(value: int) -> str:
    return format(value, ",").replace(",", " ")


def add_event(db: Session, kind: str, ref_id: uuid.UUID, actor: str, event: str, note: str | None = None) -> None:
    db.add(InteractionEvent(kind=kind, ref_id=ref_id, actor=actor, event=event, note=note))


def timeline(db: Session, kind: str, ref_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(InteractionEvent)
        .where(InteractionEvent.kind == kind, InteractionEvent.ref_id == ref_id)
        .order_by(InteractionEvent.created_at)
    )
    return [{"actor": r.actor, "event": r.event, "note": r.note, "at": r.created_at.isoformat()} for r in rows]


def find_candidate(db: Session, public_id: str) -> User:
    user = db.scalar(select(User).where(User.public_id == public_id, User.role == "candidate", User.is_active.is_(True)))
    if user is None or not has_consent(db, user.id, "profile_publication"):
        raise NotFound("Кандидат не найден")
    return user


def candidate_email(db: Session, user: User) -> str:
    profile = db.get(CandidateProfile, user.id)
    return (profile.contact_email if profile and profile.contact_email else None) or user.email


_candidate_email = candidate_email


def touch_activity(db: Session, user_id: uuid.UUID) -> None:
    """Действие кандидата, которое считается активностью для фактора «актуальность» в подборе."""
    profile = db.get(CandidateProfile, user_id)
    if profile is not None:
        profile.last_active_at = utcnow()


def _employer_email(db: Session, company: Company) -> str:
    return company.contact_email or db.get(User, company.owner_user_id).email


def _invitation_hook(db: Session, invitation: Invitation, event: str, with_candidate: bool = False) -> None:
    candidate = db.get(User, invitation.candidate_user_id)
    data = {
        "invitation": {
            "id": str(invitation.id), "title": invitation.title, "status": invitation.status,
            "salary_from": invitation.salary_from, "salary_to": invitation.salary_to,
            "need_id": str(invitation.need_id) if invitation.need_id else None,
            "decline_reason": invitation.decline_reason,
            "decline_reason_title": DECLINE_REASONS.get(invitation.decline_reason) if invitation.decline_reason else None,
        },
        "candidate_id": candidate.public_id,
    }
    if with_candidate:
        db.flush()
        data["candidate"] = candidate_json_resume(db, invitation.company_id, candidate)
    webhooks.emit(db, invitation.company_id, event, data)


def _application_hook(db: Session, application: Application, event: str, with_candidate: bool = False) -> None:
    candidate = db.get(User, application.candidate_user_id)
    need = db.get(Need, application.need_id)
    data = {
        "application": {"id": str(application.id), "status": application.status, "cover_letter": application.cover_letter},
        "vacancy": {"id": str(need.id), "title": need.title},
        "candidate_id": candidate.public_id,
    }
    if with_candidate:
        db.flush()
        data["candidate"] = candidate_json_resume(db, application.company_id, candidate)
    webhooks.emit(db, application.company_id, event, data)


def expire_if_needed(db: Session, invitation: Invitation) -> None:
    if invitation.status in ACTIVE_INVITATION and invitation.expires_at < utcnow():
        invitation.status = "expired"
        add_event(db, "invitation", invitation.id, "system", "expired")
        _invitation_hook(db, invitation, "invitation.expired")


# ------------------------------------------------------------------ приглашения


def send_invitation(db: Session, company: Company, candidate_public_id: str, data: dict) -> Invitation:
    settings = get_settings()
    trust.ensure_active(company)
    candidate = find_candidate(db, candidate_public_id)
    profile = db.get(CandidateProfile, candidate.id)
    if profile is None or not profile.open_to_offers:
        raise Conflict("Кандидат сейчас не рассматривает предложения", code="not_open_to_offers")
    if data["salary_from"] > data["salary_to"]:
        raise AppError("Нижняя граница зарплаты больше верхней", code="invalid_salary")
    need = None
    if data.get("need_id"):
        need = db.get(Need, data["need_id"])
        if need is None or need.company_id != company.id:
            raise NotFound("Потребность не найдена")
    suitable = bool(data.get("suitable_for_minors") or (need is not None and need.suitable_for_minors))
    minors.ensure_offer_allowed(db, candidate, profile, suitable)
    since = utcnow() - timedelta(days=1)
    sent_today = db.scalar(
        select(func.count()).select_from(Invitation).where(Invitation.company_id == company.id, Invitation.created_at >= since)
    )
    if sent_today >= settings.invitations_per_company_per_day:
        raise TooManyRequests("Превышен дневной лимит приглашений компании", code="invitation_limit")
    duplicate = db.scalar(
        select(Invitation).where(
            Invitation.company_id == company.id,
            Invitation.candidate_user_id == candidate.id,
            Invitation.status.in_(ACTIVE_INVITATION),
        )
    )
    if duplicate is not None:
        expire_if_needed(db, duplicate)  # истёкшее, но ещё не помеченное приглашение не мешает новому
        if duplicate.status in ACTIVE_INVITATION:
            raise Conflict("Кандидату уже отправлено действующее приглашение", code="invitation_exists")
        db.flush()

    match = _match_snapshot(db, candidate, need, data.get("selection_id"), company)
    invitation = Invitation(
        company_id=company.id,
        candidate_user_id=candidate.id,
        need_id=need.id if need else None,
        selection_id=data.get("selection_id"),
        title=data["title"],
        description=data["description"],
        salary_from=data["salary_from"],
        salary_to=data["salary_to"],
        work_format=data.get("work_format") or (need.work_format if need else None),
        contact_method=data["contact_method"],
        suitable_for_minors=suitable,
        match=match,
        expires_at=utcnow() + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    try:
        db.flush()
    except IntegrityError as exc:  # два одновременных приглашения: уникальный индекс пропустит одно
        db.rollback()
        raise Conflict("Кандидату уже отправлено действующее приглашение", code="invitation_exists") from exc
    add_event(db, "invitation", invitation.id, "employer", "sent")
    _invitation_hook(db, invitation, "invitation.created")
    send_email(
        db,
        _candidate_email(db, candidate),
        "Приглашение от %s: %s" % (company.name, invitation.title),
        "Компания %s приглашает вас: %s.\nЗарплата: %s–%s ₽.\n\nПодробности и ответ — в личном кабинете."
        % (company.name, invitation.title, rub(invitation.salary_from), rub(invitation.salary_to)),
    )
    db.commit()
    return invitation


def _match_snapshot(db: Session, candidate: User, need: Need | None, selection_id, company: Company) -> dict | None:
    """Почему пригласили: берём из подборки или считаем заново."""
    if selection_id:
        selection = db.get(Selection, selection_id)
        if selection is not None and selection.company_id == company.id:
            for row in selection.results:
                if row["candidate_id"] == candidate.public_id:
                    return row["match"]
    facts = matching.load_facts(db, user_ids=[candidate.id])
    if not facts:
        return None
    if need is not None:
        same = [f for f in facts if f.grade.specialization == need.specialization] or facts
        return matching.score_for_need(same[0], need, need_profile(need))
    return matching.score_for_category(facts[0])


def get_company_invitation(db: Session, company: Company, invitation_id: uuid.UUID) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.company_id != company.id:
        raise NotFound("Приглашение не найдено")
    expire_if_needed(db, invitation)
    return invitation


def get_candidate_invitation(db: Session, user: User, invitation_id: uuid.UUID) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.candidate_user_id != user.id:
        raise NotFound("Приглашение не найдено")
    expire_if_needed(db, invitation)
    return invitation


def mark_viewed(db: Session, invitation: Invitation) -> None:
    if invitation.status == "sent":
        invitation.status = "viewed"
        invitation.viewed_at = utcnow()
        add_event(db, "invitation", invitation.id, "candidate", "viewed")
        _invitation_hook(db, invitation, "invitation.viewed")
    db.commit()


def accept(db: Session, user: User, invitation_id: uuid.UUID, message: str | None) -> Invitation:
    invitation = get_candidate_invitation(db, user, invitation_id)
    if invitation.status not in ACTIVE_INVITATION:
        raise Conflict("Ответить можно только на действующее приглашение", code="invitation_not_active")
    company = db.get(Company, invitation.company_id)
    if company.review_status == "blocked":
        # принятие открыло бы контакты компании, заблокированной модератором
        raise Conflict("Компания заблокирована модератором: принять приглашение нельзя", code="company_blocked")
    # принятие открывает контакты: представитель мог отозвать согласие уже после приглашения
    minors.ensure_offer_allowed(db, user, db.get(CandidateProfile, user.id), bool(invitation.suitable_for_minors))
    invitation.status = "accepted"
    invitation.responded_at = utcnow()
    if invitation.viewed_at is None:
        invitation.viewed_at = invitation.responded_at
    add_event(db, "invitation", invitation.id, "candidate", "accepted", message)
    touch_activity(db, user.id)
    _invitation_hook(db, invitation, "invitation.accepted", with_candidate=True)
    send_email(
        db,
        _employer_email(db, company),
        "Кандидат %s принял приглашение «%s»" % (user.public_id, invitation.title),
        "Кандидат принял приглашение, его контакты открыты в карточке кандидата." + ("\n\nСообщение: " + message if message else ""),
    )
    db.commit()
    return invitation


def decline(db: Session, user: User, invitation_id: uuid.UUID, reason: str, comment: str | None) -> Invitation:
    if reason not in DECLINE_REASONS:
        raise AppError("Неизвестная причина отказа", code="invalid_reason")
    invitation = get_candidate_invitation(db, user, invitation_id)
    if invitation.status not in ACTIVE_INVITATION:
        raise Conflict("Ответить можно только на действующее приглашение", code="invitation_not_active")
    invitation.status = "declined"
    invitation.responded_at = utcnow()
    invitation.decline_reason = reason
    invitation.decline_comment = comment
    company = db.get(Company, invitation.company_id)
    add_event(db, "invitation", invitation.id, "candidate", "declined", DECLINE_REASONS[reason])
    touch_activity(db, user.id)
    _invitation_hook(db, invitation, "invitation.declined")
    if reason == "suspicious":
        trust.add_complaint(db, company, user, "suspicious", comment, invitation_id=invitation.id)
    send_email(
        db,
        _employer_email(db, company),
        "Кандидат %s отклонил приглашение «%s»" % (user.public_id, invitation.title),
        "Причина: %s%s" % (DECLINE_REASONS[reason], ("\nКомментарий: " + comment) if comment else ""),
    )
    db.commit()
    return invitation


def revoke_contacts(db: Session, user: User, kind: str, ref_id: uuid.UUID):
    """
    Кандидат закрывает компании доступ к своим контактам. Платформа перестаёт
    их показывать; то, что работодатель уже сохранил у себя, отозвать нельзя —
    об этом сказано кандидату в интерфейсе.
    """
    if kind == "invitation":
        obj = get_candidate_invitation(db, user, ref_id)
        if obj.status != "accepted":
            raise Conflict("Контакты открыты только по принятому приглашению", code="contacts_not_shared")
    else:
        obj = get_candidate_application(db, user, ref_id)
    if obj.contacts_revoked_at is None:
        obj.contacts_revoked_at = utcnow()
        add_event(db, kind, obj.id, "candidate", "contacts_revoked")
        audit(db, user.id, "contacts.revoked", "company", obj.company_id, **{kind: str(obj.id)})
        company = db.get(Company, obj.company_id)
        send_email(db, _employer_email(db, company), "Кандидат %s закрыл доступ к контактам" % user.public_id,
                   "Кандидат закрыл доступ к своим контактам на платформе. Связаться с ним можно новым приглашением.")
    db.commit()
    return obj


def withdraw(db: Session, company: Company, invitation_id: uuid.UUID) -> Invitation:
    invitation = get_company_invitation(db, company, invitation_id)
    if invitation.status not in ACTIVE_INVITATION:
        raise Conflict("Отозвать можно только действующее приглашение", code="invitation_not_active")
    invitation.status = "withdrawn"
    add_event(db, "invitation", invitation.id, "employer", "withdrawn")
    _invitation_hook(db, invitation, "invitation.withdrawn")
    db.commit()
    return invitation


# ------------------------------------------------------------------ отклики


def apply(db: Session, user: User, need_id: uuid.UUID, cover_letter: str | None) -> Application:
    need = db.get(Need, need_id)
    company = db.get(Company, need.company_id) if need else None
    if need is None or not need.is_published or need.status != "open" or company.review_status != "active":
        raise NotFound("Вакансия не найдена или закрыта")
    exists = db.scalar(
        select(Application.id).where(
            Application.need_id == need.id,
            Application.candidate_user_id == user.id,
            Application.status != "withdrawn",
        )
    )
    if exists:
        raise Conflict("Вы уже откликнулись на эту вакансию", code="application_exists")
    minors.ensure_offer_allowed(db, user, db.get(CandidateProfile, user.id), bool(need.suitable_for_minors))
    application = Application(
        need_id=need.id, company_id=need.company_id, candidate_user_id=user.id, cover_letter=cover_letter
    )
    db.add(application)
    try:
        db.flush()
    except IntegrityError as exc:  # два одновременных отклика: уникальный индекс пропустит один
        db.rollback()
        raise Conflict("Вы уже откликнулись на эту вакансию", code="application_exists") from exc
    add_event(db, "application", application.id, "candidate", "sent")
    touch_activity(db, user.id)
    _application_hook(db, application, "application.created", with_candidate=True)
    company = db.get(Company, need.company_id)
    send_email(
        db,
        _employer_email(db, company),
        "Новый отклик на вакансию «%s»" % need.title,
        "Кандидат %s откликнулся на вакансию. Контакты кандидата доступны в карточке отклика." % user.public_id,
    )
    db.commit()
    return application


def get_candidate_application(db: Session, user: User, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.candidate_user_id != user.id:
        raise NotFound("Отклик не найден")
    return application


def get_company_application(db: Session, company: Company, application_id: uuid.UUID) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.company_id != company.id:
        raise NotFound("Отклик не найден")
    return application


def withdraw_application(db: Session, user: User, application_id: uuid.UUID) -> Application:
    application = get_candidate_application(db, user, application_id)
    if application.status in ("withdrawn", "rejected"):
        raise Conflict("Отклик уже закрыт", code="application_closed")
    application.status = "withdrawn"
    add_event(db, "application", application.id, "candidate", "withdrawn")
    _application_hook(db, application, "application.withdrawn")
    db.commit()
    return application


def employer_mark_viewed(db: Session, application: Application) -> None:
    if application.status == "sent":
        application.status = "viewed"
        add_event(db, "application", application.id, "employer", "viewed")
    db.commit()


def employer_respond(db: Session, company: Company, application_id: uuid.UUID, status: str, comment: str | None) -> Application:
    if status not in ("invited", "rejected"):
        raise AppError("Допустимые решения: invited, rejected", code="invalid_status")
    application = get_company_application(db, company, application_id)
    if status == "invited":
        # компания на проверке после жалоб кандидатов только смотрит; отказ по отклику ничего не открывает
        trust.ensure_active(company)
    if application.status in ("withdrawn", "rejected", "invited"):
        raise Conflict("По отклику уже принято решение", code="application_closed")
    application.status = status
    application.employer_comment = comment
    add_event(db, "application", application.id, "employer", status, comment)
    _application_hook(db, application, "application.%s" % status)
    candidate = db.get(User, application.candidate_user_id)
    need = db.get(Need, application.need_id)
    send_email(
        db,
        _candidate_email(db, candidate),
        ("Приглашение на собеседование: %s" if status == "invited" else "Ответ по вакансии %s") % need.title,
        ("Компания %s приглашает вас на следующий этап." if status == "invited" else "Компания %s пока не готова продолжить.")
        % company.name
        + ("\n\nКомментарий: " + comment if comment else ""),
    )
    db.commit()
    return application
