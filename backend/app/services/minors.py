"""
Несовершеннолетние кандидаты.

Среди участников ФСП много школьников. Правила платформы:

* возраст считается по дате рождения в профиле; работодатель видит только
  отметку «несовершеннолетний», а не дату;
* младше 14 лет профиль не принимается (`too_young`);
* в 14 лет доступны только опрос, тест и категория: трудовой договор
  возможен с 15 лет (ст. 63 ТК РФ, уточнение постановщиков на Q&A),
  поэтому профиль не показывается работодателям, а приглашения и отклики
  недоступны (`too_young_for_work`);
* в 15–17 лет профиль показывается работодателям и откликаться на
  вакансии можно только после **согласия законного представителя**:
  кандидат указывает его ФИО и почту, представитель подтверждает согласие
  по ссылке из письма и по той же ссылке может его отозвать. Отзыв сразу
  убирает профиль из выдачи;
* приглашать несовершеннолетнего можно только с отметкой «подходит для
  несовершеннолетних (15–17 лет)» — лёгкий труд, сокращённое время, без
  вредных и опасных условий (ст. 63, 92, 265 ТК РФ); откликаться — только
  на такие вакансии;
* после отказа или отзыва ссылка представителя перестаёт действовать:
  чтобы снова дать согласие, кандидат запрашивает его заново;
* в 18 лет ограничения снимаются сами: возраст считается на текущую дату.

Дата рождения обязательна при прохождении опроса (`birth_date_required`):
иначе возрастные правила обходились бы пустым полем. Тест и категория
доступны с 14 лет: это оценка навыков, а не трудоустройство.
"""

import secrets
import uuid
from datetime import date, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, NotFound
from app.models import CandidateProfile, GuardianConsent, User
from app.security.passwords import allowed_tlds_text, email_domain_allowed
from app.security.tokens import hash_token
from app.services.consents import audit, has_consent, set_consent
from app.services.mailer import send_email
from app.services.ratelimit import SlidingWindowLimiter

ADULT_AGE = 18
# Возраст считается по дате в России, а не по UTC: иначе с 00:00 до 03:00 по
# Москве у кандидата с сегодняшним днём рождения возраст был бы на год меньше.
MSK = timezone(timedelta(hours=3))  # Москва, без перехода на летнее время


def today_local() -> date:
    return utcnow().astimezone(MSK).date()
MINOR_NOTE = (
    "Кандидату 15–17 лет: подходят только предложения с лёгким трудом, сокращённым рабочим временем "
    "и без вредных условий; согласие законного представителя получено"
)
guardian_limiter = SlidingWindowLimiter(limit=5, window_seconds=3600)


def age(birth_date: date | None, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    today = today or today_local()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def is_minor(profile: CandidateProfile | None, today: date | None = None) -> bool:
    years = age(profile.birth_date if profile else None, today)
    return years is not None and years < ADULT_AGE


def check_birth_date(value: date | None) -> date | None:
    """Проверка даты рождения для схемы профиля."""
    if value is None:
        return None
    years = age(value)
    if value > today_local() or years > 100:
        raise ValueError("Проверьте дату рождения")
    if years < get_settings().min_candidate_age:
        raise ValueError("Платформа доступна с %d лет" % get_settings().min_candidate_age)
    return value


def guardian_granted(db: Session, user_id: uuid.UUID) -> bool:
    row = db.get(GuardianConsent, user_id)
    return row is not None and row.status == "granted"


def below_work_age(profile: CandidateProfile | None, today: date | None = None) -> bool:
    years = age(profile.birth_date if profile else None, today)
    return years is not None and years < get_settings().min_work_age


def may_be_shown(db: Session, user_id: uuid.UUID, profile: CandidateProfile | None) -> bool:
    """Можно ли показывать профиль работодателям и откликаться от имени кандидата."""
    if below_work_age(profile):
        return False
    return not is_minor(profile) or guardian_granted(db, user_id)


def guardian_out(db: Session, user_id: uuid.UUID) -> dict | None:
    row = db.get(GuardianConsent, user_id)
    if row is None:
        return None
    return {
        "status": row.status,
        "guardian_name": row.guardian_name,
        "guardian_email": row.guardian_email,
        "requested_at": row.requested_at,
        "decided_at": row.decided_at,
        "expires_at": row.expires_at,
    }


def request_guardian_consent(db: Session, user: User, profile: CandidateProfile, name: str,
                             email: str) -> tuple[GuardianConsent, str]:
    """Запрос согласия; возвращает запись и ссылку для представителя (в демо-режиме её показывает API)."""
    if not is_minor(profile):
        raise AppError("Согласие представителя нужно только кандидатам младше 18 лет", code="not_minor")
    email = email.strip().lower()
    if not email_domain_allowed(email):
        raise AppError("Почта представителя — только в домене %s" % allowed_tlds_text(), code="email_domain_not_allowed")
    if email == user.email.lower() or email == (profile.contact_email or "").lower():
        raise AppError("Укажите почту законного представителя, а не свою", code="guardian_email_is_own")
    guardian_limiter.hit("guardian:%s" % user.id, "Слишком много запросов, повторите позже")
    token = secrets.token_urlsafe(32)
    now = utcnow()
    row = db.get(GuardianConsent, user.id)
    if row is None:
        row = GuardianConsent(user_id=user.id)
        db.add(row)
    row.guardian_name, row.guardian_email = name.strip(), email
    row.status, row.decided_at = "pending", None
    row.token_hash = hash_token(token)
    row.requested_at = now
    row.expires_at = now + timedelta(days=get_settings().guardian_link_days)
    link = "%s/guardian-consent?token=%s" % (get_settings().frontend_url.rstrip("/"), token)
    who = profile.full_name or "Ваш ребёнок"
    send_email(
        db, email, "Согласие на участие в подборе вакансий: %s" % who,
        "Здравствуйте, %s!\n\n%s зарегистрировался на платформе подбора ИТ-специалистов ФСП и указал вас как "
        "законного представителя. Чтобы его профиль увидели работодатели и он мог откликаться на стажировки "
        "и подработку, нужно ваше согласие.\n\nПодробности и решение: %s\n\nСсылка действует %d дней. По этой же "
        "ссылке согласие можно отозвать в любой момент."
        % (row.guardian_name, who, link, get_settings().guardian_link_days),
        kind="guardian_consent",
    )
    audit(db, user.id, "guardian.requested", "user", user.id)
    db.commit()
    return row, link


def _by_token(db: Session, token: str) -> GuardianConsent:
    row = db.scalar(select(GuardianConsent).where(GuardianConsent.token_hash == hash_token(token)))
    if row is None:
        raise NotFound("Ссылка недействительна: возможно, кандидат запросил согласие заново", code="guardian_link_invalid")
    return row


def guardian_view(db: Session, token: str) -> dict:
    return _view(db, _by_token(db, token))


def _view(db: Session, row: GuardianConsent) -> dict:
    profile = db.get(CandidateProfile, row.user_id)
    return {
        "candidate_name": (profile.full_name if profile and profile.full_name else "Кандидат"),
        "candidate_age": age(profile.birth_date) if profile else None,
        "guardian_name": row.guardian_name,
        "status": row.status,
        "expires_at": row.expires_at,
        "link_expired": row.status == "pending" and row.expires_at < utcnow(),
        "what": [
            "профиль показывается работодателям платформы обезличенно: инициалы, город, навыки, результат теста",
            "контакты открываются только компании, чьё приглашение кандидат принял сам",
            "приглашения возможны только на предложения с лёгким трудом и сокращённым рабочим временем",
            "согласие можно отозвать по этой ссылке в любой момент — профиль сразу скроется",
        ],
    }


def guardian_decide(db: Session, token: str, decision: str) -> dict:
    row = _by_token(db, token)
    now = utcnow()
    if decision == "grant":
        if row.status == "pending" and row.expires_at < now:
            raise Conflict("Срок ссылки истёк — попросите кандидата запросить согласие заново", code="guardian_link_expired")
        if row.status not in ("pending", "declined", "revoked"):
            return guardian_view(db, token)
        row.status = "granted"
    elif decision in ("decline", "revoke"):
        row.status = "declined" if row.status == "pending" else "revoked"
        if has_consent(db, row.user_id, "profile_publication"):
            set_consent(db, row.user_id, "profile_publication", False)
    else:
        raise AppError("Решение: grant, decline или revoke", code="invalid_decision")
    row.decided_at = now
    audit(db, None, "guardian.%s" % row.status, "user", row.user_id)
    view = _view(db, row)
    if row.status in ("declined", "revoked"):
        # отказ окончательный для этой ссылки: снова дать согласие можно только по новому запросу
        # кандидата, иначе отозванное согласие «включалось» бы старой ссылкой без срока
        row.token_hash = hash_token(secrets.token_urlsafe(32))
        view["link_closed"] = True
    db.commit()
    return view


def on_profile_changed(db: Session, user: User, profile: CandidateProfile) -> None:
    """Если кандидат оказался младше 18 без согласия представителя — профиль скрывается."""
    if not may_be_shown(db, user.id, profile) and has_consent(db, user.id, "profile_publication"):
        set_consent(db, user.id, "profile_publication", False)
        audit(db, user.id, "consent.changed", "user", user.id, kind="profile_publication", granted=False,
              reason="guardian_consent_required")


def ensure_publication_allowed(db: Session, user: User) -> None:
    profile = db.get(CandidateProfile, user.id)
    if below_work_age(profile):
        raise Conflict("Показ профиля работодателям доступен с %d лет: до этого — только тест и категория"
                       % get_settings().min_work_age, code="too_young_for_work")
    if not may_be_shown(db, user.id, profile):
        raise Conflict("До 18 лет профиль показывается работодателям после согласия законного представителя",
                       code="guardian_consent_required")


def ensure_offer_allowed(db: Session, candidate: User, profile: CandidateProfile | None, suitable: bool) -> None:
    """Приглашение или отклик несовершеннолетнего: нужно согласие представителя и подходящее предложение."""
    if below_work_age(profile):
        raise Conflict("Приглашения и отклики доступны с %d лет: до этого — только тест и категория"
                       % get_settings().min_work_age, code="too_young_for_work")
    if not is_minor(profile):
        return
    if not guardian_granted(db, candidate.id):
        raise Conflict("Нет согласия законного представителя несовершеннолетнего кандидата",
                       code="guardian_consent_required")
    if not suitable:
        raise Conflict("Кандидату меньше 18 лет: подходят только предложения с отметкой «подходит для несовершеннолетних "
                       "(15–17 лет)» — лёгкий труд, сокращённое время, без вредных условий", code="minor_offer_not_suitable")
