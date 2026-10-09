"""
Привязка ФСП ID, синхронизация достижений и их вклад в ранжирование.

Структура данных ФСП в рамках хакатона не предоставлена, поэтому набор
полей выбран по принципу «проверяемый факт, полезный работодателю»:
мероприятие, дисциплина, уровень, итог (место), роль в команде, дата и
спортивный разряд участника.

Вклад в ранжирование учитывает результативность и число соревнований
(уточнения постановщиков на встрече):

* все соревнования и дисциплины равноценны — внутреннего рейтинга
  «чемпионат выше хакатона» нет, уровень мероприятия только показывается;
* роль в команде не даёт бонуса: ФСП ID не подтверждает, кто что делал;
* участие без результата весит мало, а суммарно ограничено, чтобы
  профиль нельзя было «набить» онлайн-явками.

    вес = итог × exp(−лет / 3)
    итог: победитель 1,0; призёр 0,75; финалист 0,4; участник 0,1
    сумма участий без результата — не больше 0,3
    fsp_score = 1 − exp(−сумма весов / 1,2)

Кандидат без истории ФСП получает 0 — это отсутствие бонуса, а не штраф:
остальные компоненты ранжирования от этого не меняются.
"""

import math
import secrets
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, Forbidden, NotFound
from app.models import CandidateProfile, EmailToken, FspAchievement, FspLink, OidcState, User
from app.reference import FSP_DISCIPLINES, FSP_EVENT_LEVELS, FSP_RESULTS, FSP_SPORT_RANKS
from app.security.deps import secure_unverified_account
from app.security.passwords import allowed_tlds_text, email_domain_allowed
from app.security.tokens import hash_token
from app.services.consents import audit, has_consent, set_consent
from app.services.fsp_gateway import gateway, pkce_pair

RECENCY_YEARS = 3.0
SCORE_SCALE = 1.2
RESULT_WEIGHTS = {"winner": 1.0, "prize": 0.75, "finalist": 0.4, "participant": 0.1}
PARTICIPATION_CAP = 0.3
PODIUM = ("winner", "prize")


def callback_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + "/api/v1/fsp/link/callback"


def achievement_weight(a: FspAchievement, today: date) -> float:
    """Вес одного достижения: результативность и давность, без ранжирования соревнований."""
    years = max(0.0, (today - a.event_date).days / 365.25)
    return RESULT_WEIGHTS.get(a.result, RESULT_WEIGHTS["participant"]) * math.exp(-years / RECENCY_YEARS)


def fsp_stats(achievements: list[FspAchievement]) -> dict:
    verified = [a for a in achievements if a.verified]
    return {
        "competitions": len(verified),
        "wins": sum(1 for a in verified if a.result == "winner"),
        "podiums": sum(1 for a in verified if a.result in PODIUM),
        "finals": sum(1 for a in verified if a.result == "finalist"),
    }


def fsp_score(achievements: list[FspAchievement], specialization: str | None = None, today: date | None = None) -> dict:
    """
    Итог 0..1 для ранжирования. specialization оставлен для совместимости:
    дисциплины не ранжируются, поэтому от специализации вес не зависит.
    """
    today = today or utcnow().date()
    stats = fsp_stats(achievements)
    if not stats["competitions"]:
        return {"score": 0.0, "has_history": bool(achievements), "top": [], "stats": stats}
    weighted = sorted(
        ((achievement_weight(a, today), a) for a in achievements if a.verified),
        key=lambda x: -x[0],
    )
    results = sum(w for w, a in weighted if a.result != "participant")
    participation = min(PARTICIPATION_CAP, sum(w for w, a in weighted if a.result == "participant"))
    total = results + participation
    return {
        "score": round(1 - math.exp(-total / SCORE_SCALE), 4),
        "has_history": True,
        "top": [describe(a) | {"weight": round(w, 3)} for w, a in weighted[:3]],
        "stats": stats,
    }


def rank_title(rank: str | None) -> str | None:
    return FSP_SPORT_RANKS.get(rank) if rank else None


def describe(a: FspAchievement) -> dict:
    return {
        "event_name": a.event_name,
        "discipline": a.discipline,
        "discipline_title": FSP_DISCIPLINES.get(a.discipline, a.discipline),
        "event_level": a.event_level,
        "event_level_title": FSP_EVENT_LEVELS.get(a.event_level, a.event_level),
        "result": a.result,
        "result_title": FSP_RESULTS.get(a.result, a.result),
        "place": a.place,
        "team_role": a.team_role,
        "team_name": a.team_name,
        "event_date": a.event_date.isoformat(),
        "verified": a.verified,
        "certificate_url": a.certificate_url,
    }


def headline(achievements: list[FspAchievement], specialization: str | None = None) -> str | None:
    """Одна строка для карточки: лучший результат и сводка по числу соревнований."""
    data = fsp_score(achievements, specialization)
    if not data["top"]:
        return None
    top, stats = data["top"][0], data["stats"]
    summary = "соревнований: %d" % stats["competitions"]
    if stats["podiums"]:
        summary += ", призовых мест: %d" % stats["podiums"]
    return "%s: %s (%s); %s" % (top["result_title"], top["event_name"], top["event_date"][:4], summary)


# ------------------------------------------------------------------ привязка


def start_link(db: Session, user: User, consent: bool, redirect_after: str | None) -> str:
    if db.get(FspLink, user.id) is not None:
        raise Conflict("ФСП ID уже привязан", code="fsp_already_linked")
    if not consent and not has_consent(db, user.id, "fsp_data"):
        raise AppError("Нужно согласие на получение сведений из реестра ФСП", code="consent_required")
    if consent:
        set_consent(db, user.id, "fsp_data", True)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    db.add(
        OidcState(
            state=state,
            user_id=user.id,
            code_verifier=verifier,
            nonce=nonce,
            redirect_after=redirect_after,
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()
    return gateway().authorization_url(state, challenge, nonce, callback_uri())


def complete_link(db: Session, user: User, code: str, state: str) -> tuple[User, OidcState]:
    """
    Завершает привязку. Вызывается фронтендом с токеном пользователя, а не
    напрямую из адреса возврата ФСП ID: так привязку завершает тот же
    человек, что её начал. Иначе злоумышленник мог бы прислать жертве свою
    ссылку привязки, и ФСП ID жертвы с её достижениями оказался бы в его
    профиле (CSRF при привязке учётных записей OAuth).
    """
    row = db.get(OidcState, state)
    if row is None or row.expires_at < utcnow() or row.purpose != "link":
        raise AppError("Сеанс привязки устарел, начните заново", code="fsp_state_invalid")
    if row.user_id != user.id:
        raise Forbidden("Привязку начал другой пользователь платформы", code="fsp_state_foreign")
    db.delete(row)
    tokens = gateway().exchange_code(code, row.code_verifier, callback_uri())
    claims = gateway().verify_id_token(tokens["id_token"], row.nonce)
    fsp_id = claims["sub"]
    # привязку могли начать в двух вкладках: вторая завершается тем же ФСП ID — это не ошибка
    mine = db.get(FspLink, user.id)
    if mine is not None:
        db.commit()
        if mine.fsp_id == fsp_id:
            return user, row
        raise Conflict("ФСП ID уже привязан", code="fsp_already_linked")
    other = db.scalar(select(FspLink).where(FspLink.fsp_id == fsp_id))
    if other is not None:
        db.commit()
        raise Conflict("Этот ФСП ID уже привязан к другому профилю", code="fsp_id_taken")
    db.add(FspLink(user_id=user.id, fsp_id=_clip(fsp_id, 64), display_name=_clip(claims.get("name"), 200),
                        region=_clip(claims.get("region"), 100)))
    audit(db, user.id, "fsp.linked", "user", user.id, fsp_id=fsp_id)
    try:
        db.flush()
    except IntegrityError as exc:  # тот же ФСП ID одновременно привязывают к двум профилям
        db.rollback()
        raise Conflict("Этот ФСП ID уже привязан к другому профилю", code="fsp_id_taken") from exc
    sync(db, user.id)
    db.commit()
    return user, row


# ------------------------------------------------------------------ вход через ФСП ID

LOGIN_CODE_MINUTES = 2


def start_login(db: Session, consent: bool, redirect_after: str | None) -> str:
    """
    Вход через ФСП ID (ФСП задумывает его как единую точку входа). Тот же
    OIDC + PKCE, что и при привязке; согласия нужны, только если по итогам
    входа будет создан новый профиль кандидата.
    """
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    db.add(OidcState(state=state, purpose="login", user_id=None, code_verifier=verifier, nonce=nonce,
                     redirect_after=redirect_after, consent=consent, expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return gateway().authorization_url(state, challenge, nonce, callback_uri())


def is_login_state(db: Session, state: str) -> bool:
    row = db.get(OidcState, state)
    return row is not None and row.purpose == "login"


def complete_login(db: Session, code: str, state: str) -> tuple[str, str | None]:
    """
    Завершает вход: проверяет id_token, находит профиль по ФСП ID или почте
    (или создаёт кандидата), привязывает ФСП ID и выдаёт одноразовый код,
    который фронтенд обменивает на токены (POST /auth/fsp/exchange).
    """
    row = db.get(OidcState, state)
    if row is None or row.expires_at < utcnow() or row.purpose != "login":
        raise AppError("Сеанс входа устарел, начните заново", code="fsp_state_invalid")
    db.delete(row)
    db.commit()
    tokens = gateway().exchange_code(code, row.code_verifier, callback_uri())
    claims = gateway().verify_id_token(tokens["id_token"], row.nonce)
    fsp_id = claims["sub"]
    link = db.scalar(select(FspLink).where(FspLink.fsp_id == fsp_id))
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        email = (claims.get("email") or "").strip().lower()
        if not email or not claims.get("email_verified"):
            raise AppError("ФСП ID не передал подтверждённый адрес почты", code="fsp_email_missing")
        if not email_domain_allowed(email):
            raise AppError("Вход доступен только с почтой в домене %s" % allowed_tlds_text(), code="email_domain_not_allowed")
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            if not row.consent:
                raise AppError("Для первого входа нужны согласия на обработку данных и получение сведений из реестра ФСП",
                               code="consent_required")
            user = User(email=email, role="candidate", email_verified=True)
            db.add(user)
            db.flush()
            db.add(CandidateProfile(user_id=user.id, contact_email=email, full_name=claims.get("name")))
            set_consent(db, user.id, "pd_processing", True)
            audit(db, user.id, "user.registered", "user", user.id, role="candidate", via="fsp_id")
        elif user.role != "candidate":
            raise Conflict("Вход через ФСП ID доступен соискателям", code="fsp_login_candidates_only")
        elif db.get(FspLink, user.id) is not None:
            raise Conflict("К профилю с этой почтой уже привязан другой ФСП ID", code="fsp_id_taken")
        if not row.consent and not has_consent(db, user.id, "fsp_data"):
            raise AppError("Нужно согласие на получение сведений из реестра ФСП", code="consent_required")
        set_consent(db, user.id, "fsp_data", True)
        # почту подтвердил ФСП ID; пароль неподтверждённой учётки мог задать посторонний
        secure_unverified_account(db, user, via="fsp_id")
        db.add(FspLink(user_id=user.id, fsp_id=_clip(fsp_id, 64), display_name=_clip(claims.get("name"), 200),
                        region=_clip(claims.get("region"), 100)))
        audit(db, user.id, "fsp.linked", "user", user.id, fsp_id=fsp_id, via="login")
        db.flush()
        sync(db, user.id)
    if user is None or not user.is_active:
        raise AppError("Учётная запись отключена", code="account_disabled", status_code=403)
    login_code = secrets.token_urlsafe(32)
    db.add(EmailToken(user_id=user.id, purpose="fsp_login", token_hash=hash_token(login_code),
                      expires_at=utcnow() + timedelta(minutes=LOGIN_CODE_MINUTES)))
    audit(db, user.id, "auth.login", "user", user.id, via="fsp_id")
    db.commit()
    return login_code, row.redirect_after


def exchange_login_code(db: Session, code: str) -> User:
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(code), EmailToken.purpose == "fsp_login"))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise AppError("Код входа недействителен или устарел", code="invalid_login_code", status_code=401)
    row.used_at = utcnow()
    user = db.get(User, row.user_id)
    user.last_login_at = utcnow()
    return user


def _clip(value, length: int):
    return value[:length] if isinstance(value, str) else value


def sync(db: Session, user_id: uuid.UUID) -> FspLink:
    link = db.get(FspLink, user_id)
    if link is None:
        raise NotFound("ФСП ID не привязан")
    try:
        person = gateway().participant(link.fsp_id)
        items = gateway().achievements(link.fsp_id)
    except AppError as exc:
        link.sync_error = exc.message[:255]
        return link
    link.display_name = _clip(person.get("name"), 200) or link.display_name
    link.region = _clip(person.get("region"), 100) or link.region
    link.sport_rank = _clip(person.get("sport_rank"), 10)
    seen = set()
    for item in items:
        seen.add(item["id"])
        row = db.scalar(
            select(FspAchievement).where(FspAchievement.user_id == user_id, FspAchievement.external_id == item["id"])
        )
        if row is None:
            row = FspAchievement(user_id=user_id, external_id=item["id"])
            db.add(row)
        # данные внешнего реестра обрезаются по длине колонок: в PostgreSQL длинная строка — ошибка
        row.event_name = _clip(item["event_name"], 255)
        row.discipline = _clip(item["discipline"], 60)
        row.event_level = _clip(item["event_level"], 20)
        row.place = item.get("place")
        row.result = _clip(item["result"], 20)
        row.team_role = _clip(item.get("team_role"), 20)
        row.team_name = _clip(item.get("team_name"), 120)
        row.event_date = date.fromisoformat(item["event_date"])
        row.verified = bool(item.get("verified", True))
        row.certificate_url = _clip(item.get("certificate_url"), 255)
        row.raw = item
    stale = select(FspAchievement.id).where(FspAchievement.user_id == user_id)
    if seen:
        stale = stale.where(FspAchievement.external_id.not_in(seen))
    for achievement_id in list(db.scalars(stale)):
        db.execute(delete(FspAchievement).where(FspAchievement.id == achievement_id))
    link.last_sync_at = utcnow()
    link.sync_error = None
    return link


def unlink(db: Session, user: User) -> None:
    link = db.get(FspLink, user.id)
    if link is None:
        raise NotFound("ФСП ID не привязан")
    db.execute(delete(FspAchievement).where(FspAchievement.user_id == user.id))
    db.delete(link)
    audit(db, user.id, "fsp.unlinked", "user", user.id)
    db.commit()


def achievements_of(db: Session, user_id: uuid.UUID) -> list[FspAchievement]:
    return list(
        db.scalars(select(FspAchievement).where(FspAchievement.user_id == user_id).order_by(FspAchievement.event_date.desc()))
    )


def link_of(db: Session, user_id: uuid.UUID) -> FspLink | None:
    return db.get(FspLink, user_id)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
