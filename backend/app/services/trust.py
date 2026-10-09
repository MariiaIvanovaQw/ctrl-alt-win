"""
Защита от фиктивных вакансий и недобросовестных работодателей (MVP).

ТЗ выносит верификацию компаний и модерацию за рамки MVP, поэтому здесь
только то, что работает без внешних реестров и ручного труда, на
сигналах самой платформы:

* **Жалобы кандидатов** — на приглашение или вакансию; отказ от
  приглашения с причиной «подозрительное предложение» тоже жалоба.
* **Правдоподобие вилки** — слишком широкая вилка или нижняя граница
  намного выше ожиданий кандидатов категории — частые признаки
  «приманки». Это предупреждение кандидату, а не запрет.
* **Показатели компании для кандидата** — сколько дней на платформе,
  сколько приглашений отправлено, доля принятых, жалобы, проверена ли.
* **Добровольная проверка компании** — компания с корректным ИНН
  запрашивает метку «Компания проверена», модератор сверяет ИНН и
  название с ЕГРЮЛ. Без метки компания работает как обычно; смена ИНН или
  названия снимает метку.
* **Автоматическая приостановка** — если за 30 дней не меньше трёх
  разных кандидатов, которые с компанией взаимодействовали (получили от
  неё приглашение или откликнулись на её вакансию), пожаловались на неё и
  это не меньше 20 % ответов кандидатов, компания уходит на проверку: не
  может отправлять приглашения и публиковать вакансии, её вакансии скрыты
  из общего списка. Жалобы остальных кандидатов видит модератор, но
  автоматически они компанию не останавливают: иначе один человек мог бы
  приостановить любую компанию жалобами на её вакансии. Вернуть или
  заблокировать компанию может модератор (роль admin); заблокированная
  компания теряет и доступ к данным кандидатов.

Концепция развития (проверка по ЕГРЮЛ, домен почты, репутация и т. д.) —
docs/documentation.md, раздел 3.6.
"""

import statistics
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Forbidden
from app.models import Application, CandidateGrade, CandidateProfile, Company, Complaint, Invitation, User
from app.services.consents import audit

COMPLAINT_REASONS = {
    "suspicious": "Подозрительное предложение",
    "fake_vacancy": "Вакансии на самом деле нет",
    "salary_mismatch": "Условия не совпадают с указанными",
    "spam": "Рассылка, не связанная с работой",
    "payment_request": "Просят заплатить или купить обучение",
    "other": "Другое",
}
REVIEW_STATUSES = ("active", "on_review", "blocked")


def ensure_active(company: Company) -> None:
    """Компания на проверке или заблокированная не пишет кандидатам и не публикует вакансии."""
    if company.review_status != "active":
        raise Forbidden(
            "Компания на проверке после жалоб кандидатов: приглашения и публикация вакансий временно недоступны"
            if company.review_status == "on_review"
            else "Компания заблокирована модератором",
            code="company_" + company.review_status,
        )


def ensure_not_blocked(company: Company) -> None:
    """
    Заблокированная модератором компания теряет доступ к данным кандидатов:
    поиску, карточкам, PDF, выгрузке и подборкам. Компания на проверке
    (on_review) данные смотреть может, но не пишет кандидатам и не публикует
    вакансии (ensure_active).
    """
    if company.review_status == "blocked":
        raise Forbidden("Компания заблокирована модератором: доступ к данным кандидатов закрыт", code="company_blocked")


def add_complaint(db: Session, company: Company, reporter: User, reason: str, comment: str | None = None,
                  invitation_id=None, need_id=None) -> Complaint:
    if reason not in COMPLAINT_REASONS:
        raise AppError("Неизвестная причина жалобы", code="invalid_reason")
    duplicate = db.scalar(
        select(Complaint.id).where(
            Complaint.company_id == company.id,
            Complaint.reporter_user_id == reporter.id,
            Complaint.invitation_id == invitation_id if invitation_id else Complaint.need_id == need_id,
        )
    )
    if duplicate:
        raise AppError("Жалоба уже отправлена", code="complaint_exists", status_code=409)
    complaint = Complaint(company_id=company.id, reporter_user_id=reporter.id, reason=reason, comment=comment,
                          invitation_id=invitation_id, need_id=need_id)
    db.add(complaint)
    company.complaints += 1
    db.flush()
    audit(db, reporter.id, "company.complaint", "company", company.id, reason=reason)
    evaluate(db, company)
    return complaint


def interacted_candidates(db: Session, company_id) -> set:
    """Кандидаты, которые получили от компании приглашение или откликнулись на её вакансию."""
    invited = db.scalars(select(Invitation.candidate_user_id).where(Invitation.company_id == company_id))
    applied = db.scalars(select(Application.candidate_user_id).where(Application.company_id == company_id))
    return set(invited) | set(applied)


def _window_stats(db: Session, company: Company) -> tuple[int, int]:
    """
    Жалобы за окно — число разных авторов, которые взаимодействовали с
    компанией: получили приглашение или откликнулись на вакансию.
    """
    since = utcnow() - timedelta(days=get_settings().trust_window_days)
    invited = select(Invitation.candidate_user_id).where(Invitation.company_id == company.id)
    applied = select(Application.candidate_user_id).where(Application.company_id == company.id)
    complaints = db.scalar(
        select(func.count(func.distinct(Complaint.reporter_user_id))).where(
            Complaint.company_id == company.id,
            Complaint.created_at >= since,
            Complaint.reporter_user_id.in_(invited.union(applied)),
        )
    )
    responses = db.scalar(
        select(func.count())
        .select_from(Invitation)
        .where(
            Invitation.company_id == company.id,
            Invitation.responded_at >= since,
            Invitation.status.in_(("accepted", "declined")),
        )
    )
    return complaints or 0, responses or 0


def evaluate(db: Session, company: Company) -> None:
    """Автоматическая приостановка по жалобам. Снять её может только модератор."""
    if company.review_status != "active":
        return
    settings = get_settings()
    complaints, responses = _window_stats(db, company)
    share = complaints / max(responses, complaints, 1)
    if complaints >= settings.trust_review_complaints and share >= settings.trust_review_share:
        company.review_status = "on_review"
        company.review_reason = "Автоматически: жалобы %d кандидатов за %d дней (%.0f %% ответов кандидатов)" % (
            complaints, settings.trust_window_days, share * 100)
        company.reviewed_at = utcnow()
        audit(db, None, "company.auto_review", "company", company.id, complaints=complaints, responses=responses)


VERIFICATION_TITLES = {
    "none": "Не проверена",
    "requested": "Проверка запрошена",
    "verified": "Компания проверена",
    "rejected": "Проверка не пройдена",
}


def inn_valid(inn: str | None) -> bool:
    """Контрольные разряды ИНН (10 цифр — организация, 12 — ИП/физлицо)."""
    if not inn or not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(x) for x in inn]

    def check(weights):
        return sum(w * x for w, x in zip(weights, d, strict=False)) % 11 % 10  # весов меньше, чем цифр

    if len(inn) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def request_verification(db: Session, user: User, company: Company) -> Company:
    if company.verification_status == "verified":
        raise AppError("Компания уже проверена", code="already_verified", status_code=409)
    if not inn_valid(company.inn):
        raise AppError("Укажите корректный ИНН компании: по нему модератор сверит данные с ЕГРЮЛ",
                       code="inn_invalid")
    company.verification_status = "requested"
    company.verification_requested_at = utcnow()
    company.verification_comment = None
    audit(db, user.id, "company.verification_requested", "company", company.id)
    db.commit()
    return company


def decide_verification(db: Session, moderator: User, company: Company, approve: bool, comment: str | None) -> Company:
    if company.verification_status != "requested":
        raise AppError("Компания не запрашивала проверку", code="verification_not_requested", status_code=409)
    company.verification_status = "verified" if approve else "rejected"
    company.verified = approve
    company.verified_at = utcnow() if approve else None
    company.verification_comment = comment
    audit(db, moderator.id, "company.verification_decided", "company", company.id, approve=approve)
    db.commit()
    return company


def on_company_edited(company: Company, old_name: str | None, old_inn: str | None) -> None:
    """Метка относится к конкретным ИНН и названию: при их смене её нужно подтвердить заново."""
    if company.verification_status in ("verified", "requested") and (company.name != old_name or company.inn != old_inn):
        company.verified = False
        company.verified_at = None
        company.verification_status = "none"
        company.verification_comment = "ИНН или название изменились — запросите проверку заново"


def review(db: Session, moderator: User, company: Company, decision: str, comment: str | None) -> Company:
    if decision not in ("restore", "block"):
        raise AppError("Решение: restore или block", code="invalid_decision")
    company.review_status = "active" if decision == "restore" else "blocked"
    company.review_reason = comment
    company.reviewed_at = utcnow()
    audit(db, moderator.id, "company.reviewed", "company", company.id, decision=decision)
    db.commit()
    return company


def market_expectation(db: Session, specialization: str, level: str) -> int | None:
    """90-й перцентиль ожиданий кандидатов категории — верх «рыночного» диапазона."""
    values = sorted(
        v
        for v in db.scalars(
            select(CandidateProfile.salary_expectation)
            .join(CandidateGrade, CandidateGrade.user_id == CandidateProfile.user_id)
            .where(
                CandidateGrade.specialization == specialization,
                CandidateGrade.level == level,
                CandidateProfile.salary_expectation.is_not(None),
            )
        )
        if v
    )
    if len(values) < 5:
        return None
    return int(statistics.quantiles(values, n=10)[-1])


def salary_warnings(db: Session, salary_from: int, salary_to: int, specialization: str | None, level: str | None) -> list[str]:
    settings = get_settings()
    warnings = []
    if salary_from and salary_to > salary_from * settings.salary_max_ratio:
        warnings.append("Очень широкая вилка зарплаты: верхняя граница больше нижней в %.1f раза" % (salary_to / salary_from))
    if specialization and level:
        market = market_expectation(db, specialization, level)
        if market and salary_from > market * settings.salary_market_ratio:
            warnings.append(
                "Нижняя граница вилки намного выше ожиданий кандидатов этой категории — уточните условия до начала общения"
            )
    return warnings


def company_trust(db: Session, company: Company) -> dict:
    """Показатели компании, которые видит кандидат в приглашении и вакансии."""
    settings = get_settings()
    sent = db.scalar(select(func.count()).select_from(Invitation).where(Invitation.company_id == company.id)) or 0
    accepted = db.scalar(
        select(func.count()).select_from(Invitation).where(Invitation.company_id == company.id, Invitation.status == "accepted")
    ) or 0
    declined = db.scalar(
        select(func.count()).select_from(Invitation).where(Invitation.company_id == company.id, Invitation.status == "declined")
    ) or 0
    complaints, _responses = _window_stats(db, company)
    days = max(0, (utcnow() - company.created_at).days)
    warnings = []
    if company.review_status == "on_review":
        warnings.append("Компания на проверке после жалоб кандидатов")
    if complaints:
        warnings.append("Жалоб кандидатов за %d дней: %d" % (settings.trust_window_days, complaints))
    if days < 7:
        warnings.append("Компания зарегистрирована недавно")
    if not company.description:
        warnings.append("Компания не заполнила описание")
    return {
        "verified": company.verified,
        "verification_title": VERIFICATION_TITLES["verified" if company.verified else "none"],
        "review_status": company.review_status,
        "days_on_platform": days,
        "invitations_sent": sent,
        "acceptance_rate": round(accepted / (accepted + declined), 2) if accepted + declined else None,
        "complaints_recent": complaints,
        "warnings": warnings,
    }
