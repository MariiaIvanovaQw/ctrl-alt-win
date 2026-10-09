"""
Регистрация, подтверждение почты, вход, восстановление пароля и выдача
токенов (локальный режим).

В режиме keycloak эти операции выполняет Keycloak, а API принимает его
токены; здесь остаётся только /me.
"""

import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, Forbidden, Unauthorized, errors
from app.models import CandidateProfile, EmailToken, RefreshToken, User
from app.security.deps import DB, CurrentUser
from app.security.passwords import (
    allowed_tlds_text,
    email_domain_allowed,
    hash_password,
    password_problems,
    verify_password,
)
from app.security.tokens import hash_token, issue_access_token, new_refresh_token
from app.services import fsp as fsp_service
from app.services import tasks as tasks_service
from app.services.consents import audit, set_consent
from app.services.mailer import send_email
from app.services.ratelimit import client_ip, login_limiter, password_limiter, register_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Аутентификация"])

TOKEN_FIELD = Field(min_length=10, max_length=200)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["candidate", "employer"]
    consent_pd_processing: bool = Field(description="Согласие на обработку персональных данных (обязательно)")


class MessageOut(BaseModel):
    message: str


class RegisterOut(MessageOut):
    email_verification_required: bool
    dev_verification_link: str | None = Field(
        None, description="Только в демо-режиме: ссылка из письма подтверждения (подтверждение почты на демо не обязательно)"
    )


class VerifyIn(BaseModel):
    token: str = TOKEN_FIELD


class ResendIn(BaseModel):
    email: EmailStr


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


class MeOut(BaseModel):
    id: str
    email: str
    role: str
    email_verified: bool
    public_id: str
    auth_mode: str
    demo_account: bool = Field(False, description="Демо-учётная запись: удалить её и сменить пароль нельзя")
    has_password: bool = Field(True, description="Есть пароль (нет — вход только через ФСП ID; задать пароль можно восстановлением)")


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = TOKEN_FIELD
    password: str = Field(min_length=8, max_length=128)


class ChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _require_local_mode() -> None:
    if get_settings().auth_mode != "local":
        raise Conflict("Учётными записями управляет Keycloak", code="managed_by_keycloak")


def _issue_verification(db, user: User) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    db.add(
        EmailToken(
            user_id=user.id,
            purpose="verify",
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.email_verification_ttl_hours),
        )
    )
    link = "%s/api/v1/auth/verify-email?token=%s" % (settings.public_base_url.rstrip("/"), token)
    send_email(
        db,
        user.email,
        "Подтверждение адреса электронной почты",
        "Здравствуйте!\n\nЧтобы завершить регистрацию на платформе, перейдите по ссылке:\n%s\n\n"
        "Ссылка действует %d часа. Если вы не регистрировались, просто проигнорируйте письмо."
        % (link, settings.email_verification_ttl_hours),
        kind="verify_email",
    )
    return link


def _token_pair(db, user: User, family_id=None) -> TokenOut:
    settings = get_settings()
    access, expires_in = issue_access_token(user)
    refresh, refresh_hash = new_refresh_token()
    ttl = timedelta(days=settings.refresh_token_ttl_days)
    row = RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=utcnow() + ttl)
    if family_id is not None:
        row.family_id = family_id
    db.add(row)
    return TokenOut(
        access_token=access,
        expires_in=expires_in,
        refresh_token=refresh,
        refresh_expires_in=int(ttl.total_seconds()),
    )


def revoke_sessions(db, user_id) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))


@router.post("/register", response_model=RegisterOut, status_code=201, responses=errors(400, 429),
             summary="Регистрация по электронной почте")
def register(body: RegisterIn, request: Request, db: DB):
    """
    Создаёт учётную запись и отправляет письмо со ссылкой подтверждения.

    Ответ одинаков и для нового, и для уже занятого адреса — так по форме
    регистрации нельзя выяснить, кто зарегистрирован. Владельцу занятого
    адреса уходит письмо с напоминанием. В демо-режиме для новой учётной
    записи ответ содержит ссылку подтверждения (`dev_verification_link`).
    """
    _require_local_mode()
    register_limiter.hit(client_ip(request))
    if not body.consent_pd_processing:
        raise AppError("Без согласия на обработку персональных данных регистрация невозможна", code="consent_required")
    if not email_domain_allowed(body.email):
        raise AppError(
            "Регистрация доступна только с почтой в домене %s" % allowed_tlds_text(),
            code="email_domain_not_allowed",
            details={"allowed": get_settings().email_allowed_tlds},
        )
    problems = password_problems(body.password)
    if problems:
        raise AppError("Пароль не соответствует требованиям: " + ", ".join(problems), code="weak_password")
    email = body.email.lower()
    link = None
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        send_email(
            db,
            email,
            "Попытка повторной регистрации",
            "На этот адрес уже зарегистрирована учётная запись. Если это были вы — войдите или восстановите "
            "пароль на странице входа («Забыли пароль?»).",
        )
        db.commit()
    else:
        user = User(email=email, role=body.role, password_hash=hash_password(body.password))
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # тот же адрес одновременно зарегистрировал параллельный запрос: ответ тот же, что
            # и для занятого адреса, чтобы не раскрывать, есть ли учётная запись
            db.rollback()
            user = None
        if user is not None:
            if body.role == "candidate":
                db.add(CandidateProfile(user_id=user.id, contact_email=email))
            set_consent(db, user.id, "pd_processing", True)
            link = _issue_verification(db, user)
            audit(db, user.id, "user.registered", "user", user.id, role=body.role)
            db.commit()
    settings = get_settings()
    return RegisterOut(
        message="Проверьте почту: мы отправили ссылку для подтверждения адреса",
        email_verification_required=settings.require_email_verification,
        dev_verification_link=link if settings.demo_mode else None,
    )


def _verify(db, token: str) -> User:
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(token), EmailToken.purpose == "verify"))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise AppError("Ссылка подтверждения недействительна или устарела", code="invalid_verification_token")
    user = db.get(User, row.user_id)
    row.used_at = utcnow()
    user.email_verified = True
    audit(db, user.id, "user.email_verified", "user", user.id)
    db.commit()
    return user


@router.post("/verify-email", response_model=MessageOut, responses=errors(400), summary="Подтверждение адреса (из приложения)")
def verify_email(body: VerifyIn, db: DB):
    _require_local_mode()
    _verify(db, body.token)
    return MessageOut(message="Адрес подтверждён, можно войти")


@router.get("/verify-email", response_class=HTMLResponse, responses=errors(400), summary="Подтверждение адреса (ссылка из письма)")
def verify_email_link(token: str, db: DB):
    _require_local_mode()
    _verify(db, token)
    login_url = get_settings().frontend_url.rstrip("/") + "/login?verified=1"
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Адрес подтверждён</title>"
        f"<meta http-equiv='refresh' content='2;url={login_url}'>"
        "<body style='font-family:sans-serif;max-width:480px;margin:64px auto'>"
        "<h2>Адрес подтверждён</h2><p>Теперь можно войти на платформу.</p>"
        f"<p><a href='{login_url}'>Перейти ко входу</a></p></body>"
    )


@router.post("/resend-verification", response_model=RegisterOut, responses=errors(429), summary="Повторная отправка письма")
def resend_verification(body: ResendIn, request: Request, db: DB):
    _require_local_mode()
    register_limiter.hit(client_ip(request))
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    link = None
    if user is not None and not user.email_verified:
        link = _issue_verification(db, user)
        db.commit()
    settings = get_settings()
    return RegisterOut(
        message="Если адрес зарегистрирован и не подтверждён, письмо отправлено повторно",
        email_verification_required=settings.require_email_verification,
        dev_verification_link=link if settings.demo_mode else None,
    )


@router.post("/login", response_model=TokenOut, responses=errors(401, 403, 429), summary="Вход по почте и паролю")
def login(body: LoginIn, request: Request, db: DB):
    """
    Неудачные попытки ограничены для пары «почта + IP» и для IP в целом.
    Посторонний не может заблокировать чужой вход: счётчика только по
    адресу нет.
    """
    _require_local_mode()
    settings = get_settings()
    email = body.email.lower()
    ip = client_ip(request)
    pair_key, ip_key = "login:%s|%s" % (email, ip), "login-ip:%s" % ip
    login_limiter.check(pair_key, limit=settings.login_failures_per_account_ip)
    login_limiter.check(ip_key, "Слишком много неудачных входов с вашего адреса, повторите позже",
                        limit=settings.login_failures_per_ip)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        login_limiter.add(pair_key)
        login_limiter.add(ip_key)
        raise Unauthorized("Неверная почта или пароль", code="invalid_credentials")
    if settings.require_email_verification and not user.email_verified:
        raise AppError("Подтвердите адрес почты по ссылке из письма", code="email_not_verified", status_code=403)
    login_limiter.reset(pair_key)
    user.last_login_at = utcnow()
    tokens = _token_pair(db, user)
    if user.role == "candidate":
        # вход — естественный момент «периодически предложить» регулярное задание
        tasks_service.offer_due_task(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenOut, responses=errors(401), summary="Обновление токенов (с ротацией)")
def refresh(body: RefreshIn, db: DB):
    """
    Каждый обмен выдаёт новый refresh-токен и гасит предыдущий. Повторное
    предъявление погашенного токена — признак утечки: отзывается вся
    цепочка, и пользователю придётся войти заново.
    """
    _require_local_mode()
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    now = utcnow()
    if row is None:
        raise Unauthorized("Недействительный refresh-токен", code="invalid_refresh_token")

    def reuse_detected():
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit(db, row.user_id, "auth.refresh_reuse_detected", "user", row.user_id)
        db.commit()
        return Unauthorized("Токен уже использован: сессия завершена", code="refresh_token_reused")

    if row.used_at is not None or row.revoked_at is not None:
        raise reuse_detected()
    if row.expires_at < now:
        raise Unauthorized("Срок действия refresh-токена истёк", code="refresh_token_expired")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Пользователь не найден или отключён")
    # Погашение атомарно: из двух одновременных запросов с одним токеном (украденный и
    # настоящий) новую пару получит один, второй — признак утечки, цепочка отзывается.
    claimed = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.used_at.is_(None), RefreshToken.revoked_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        raise reuse_detected()
    tokens = _token_pair(db, user, family_id=row.family_id)
    db.commit()
    return tokens


# ------------------------------------------------------------------ пароль


@router.post("/password/forgot", response_model=MessageOut, responses=errors(429), summary="Восстановление пароля: письмо со ссылкой")
def forgot_password(body: ForgotIn, request: Request, db: DB):
    """
    Отправляет на адрес ссылку для задания нового пароля (действует
    password_reset_ttl_minutes минут). Ответ одинаков для любого адреса.
    Ссылка ведёт на страницу фронтенда `/reset-password?token=…`. Учётная
    запись, созданная входом через ФСП ID, так же может задать пароль.
    Демо-учётным записям пароль не меняется.
    """
    _require_local_mode()
    email = body.email.lower()
    password_limiter.hit("forgot-ip:%s" % client_ip(request))
    password_limiter.hit("forgot:%s" % email)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_active and not user.is_demo:
        now = utcnow()
        db.execute(
            update(EmailToken)
            .where(EmailToken.user_id == user.id, EmailToken.purpose == "reset", EmailToken.used_at.is_(None))
            .values(used_at=now)
        )
        token = secrets.token_urlsafe(32)
        minutes = get_settings().password_reset_ttl_minutes
        db.add(EmailToken(user_id=user.id, purpose="reset", token_hash=hash_token(token),
                          expires_at=now + timedelta(minutes=minutes)))
        link = "%s/reset-password?token=%s" % (get_settings().frontend_url.rstrip("/"), token)
        send_email(
            db, user.email, "Восстановление пароля",
            "Здравствуйте!\n\nЧтобы задать новый пароль, перейдите по ссылке:\n%s\n\nСсылка действует %d минут. "
            "Если вы не запрашивали восстановление, просто проигнорируйте письмо — пароль не изменится." % (link, minutes),
            kind="password_reset",
        )
        audit(db, user.id, "auth.password_reset_requested", "user", user.id)
        db.commit()
    return MessageOut(message="Если адрес зарегистрирован, мы отправили на него ссылку для восстановления пароля")


@router.post("/password/reset", response_model=MessageOut, responses=errors(400), summary="Восстановление пароля: новый пароль по ссылке")
def reset_password(body: ResetIn, db: DB):
    """
    Задаёт новый пароль по ссылке из письма. Переход по ссылке доказывает
    владение адресом, поэтому почта считается подтверждённой. Все сессии
    пользователя завершаются.
    """
    _require_local_mode()
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(body.token), EmailToken.purpose == "reset"))
    user = db.get(User, row.user_id) if row is not None else None
    if row is None or row.used_at is not None or row.expires_at < utcnow() or user is None or not user.is_active or user.is_demo:
        raise AppError("Ссылка восстановления недействительна или устарела", code="invalid_reset_token")
    problems = password_problems(body.password)
    if problems:
        raise AppError("Пароль не соответствует требованиям: " + ", ".join(problems), code="weak_password")
    row.used_at = utcnow()
    user.password_hash = hash_password(body.password)
    user.email_verified = True
    revoke_sessions(db, user.id)
    audit(db, user.id, "auth.password_reset", "user", user.id)
    send_email(db, user.email, "Пароль изменён",
               "Пароль от вашей учётной записи на платформе изменён. Если это были не вы — восстановите пароль "
               "на странице входа и напишите в поддержку.")
    db.commit()
    return MessageOut(message="Пароль изменён, войдите с новым паролем")


@router.post("/password/change", response_model=TokenOut, responses=errors(400, 401, 403, 409, 429),
             summary="Смена пароля (для вошедшего пользователя)")
def change_password(body: ChangeIn, user: CurrentUser, db: DB):
    """
    Нужен текущий пароль. Остальные сессии завершаются, в ответе — новая
    пара токенов для текущей. Если пароля нет (вход через ФСП ID) —
    `use_password_reset`: задайте пароль восстановлением.
    """
    _require_local_mode()
    if user.is_demo:
        raise Forbidden("Демо-учётной записи нельзя сменить пароль: ею пользуются все посетители стенда", code="demo_account")
    if not user.password_hash:
        raise Conflict("Пароль не задан: задайте его через восстановление пароля", code="use_password_reset")
    key = "change:%s" % user.id
    login_limiter.check(key)
    if not verify_password(body.current_password, user.password_hash):
        login_limiter.add(key)
        raise AppError("Текущий пароль указан неверно", code="invalid_current_password")
    problems = password_problems(body.new_password)
    if problems:
        raise AppError("Пароль не соответствует требованиям: " + ", ".join(problems), code="weak_password")
    login_limiter.reset(key)
    user.password_hash = hash_password(body.new_password)
    revoke_sessions(db, user.id)
    audit(db, user.id, "auth.password_changed", "user", user.id)
    tokens = _token_pair(db, user)
    db.commit()
    return tokens


# ------------------------------------------------------------------ ФСП ID


class FspLoginIn(BaseModel):
    consent_pd_processing: bool = Field(False, description="Согласие на обработку ПДн — нужно, если профиль создаётся впервые")
    consent_fsp_data: bool = Field(False, description="Согласие на получение сведений из реестра ФСП")
    redirect_after: str | None = Field(None, max_length=255, pattern=r"^/([^/\\\s]\S*)?$",
                                       description="Путь фронтенда после входа")


class FspCodeIn(BaseModel):
    code: str = Field(min_length=10, max_length=128)


class AuthorizationUrlOut(BaseModel):
    authorization_url: str


@router.post("/fsp/start", response_model=AuthorizationUrlOut, responses=errors(429, 503), summary="Вход через ФСП ID: адрес входа")
def fsp_login_start(body: FspLoginIn, request: Request, db: DB):
    """
    Вход соискателя через ФСП ID (OpenID Connect + PKCE). После входа ФСП ID
    возвращает пользователя на фронтенд `/login/fsp?code=…`; код меняется на
    токены методом `/auth/fsp/exchange`. Если профиля с этим ФСП ID или почтой
    нет, он создаётся — для этого нужны оба согласия.
    """
    _require_local_mode()
    login_limiter.hit("fsp:" + client_ip(request))
    url = fsp_service.start_login(db, body.consent_pd_processing and body.consent_fsp_data, body.redirect_after)
    return {"authorization_url": url}


@router.post("/fsp/exchange", response_model=TokenOut, responses=errors(401, 429), summary="Вход через ФСП ID: обмен кода на токены")
def fsp_login_exchange(body: FspCodeIn, request: Request, db: DB):
    _require_local_mode()
    login_limiter.hit("fsp-exchange:" + client_ip(request))
    user = fsp_service.exchange_login_code(db, body.code)
    tokens = _token_pair(db, user)
    if user.role == "candidate":
        tasks_service.offer_due_task(db, user)
    db.commit()
    return tokens


@router.post("/logout", response_model=MessageOut, summary="Выход: отзыв цепочки refresh-токенов")
def logout(body: RefreshIn, db: DB):
    _require_local_mode()
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if row is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        db.commit()
    return MessageOut(message="Сессия завершена")


@router.get("/me", response_model=MeOut, summary="Текущий пользователь")
def me(user: CurrentUser):
    return MeOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        email_verified=user.email_verified,
        public_id=user.public_id,
        auth_mode=get_settings().auth_mode,
        demo_account=bool(user.is_demo),
        has_password=bool(user.password_hash),
    )
