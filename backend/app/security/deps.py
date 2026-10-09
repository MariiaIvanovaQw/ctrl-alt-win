"""Зависимости FastAPI: текущий пользователь и проверка роли."""

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.errors import Forbidden, Unauthorized
from app.models import CandidateProfile, User
from app.security.passwords import allowed_tlds_text, email_domain_allowed
from app.security.tokens import decode_access_token, roles_from_claims

bearer = HTTPBearer(auto_error=False, description="JWT из /api/v1/auth/login или из Keycloak")

DB = Annotated[Session, Depends(get_db)]


def secure_unverified_account(db: Session, user: User, via: str) -> None:
    """
    Защита от предзахвата учётной записи.

    Кто угодно может зарегистрировать чужой адрес и не подтвердить его. Когда
    настоящий владелец позже входит через ФСП ID или Keycloak с подтверждённой
    почтой, учётная запись переходит к нему, а пароль, заданный при
    регистрации, мог быть задан посторонним. Поэтому такой пароль стирается и
    все сессии завершаются; владелец входит через внешний провайдер или
    задаёт пароль восстановлением.
    """
    if user.email_verified:
        return
    from app.models import RefreshToken
    from app.services.consents import audit

    if user.password_hash:
        user.password_hash = None
        audit(db, user.id, "auth.unverified_password_cleared", "user", user.id, via=via)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    user.email_verified = True


def _provision_external_user(db: Session, claims: dict) -> User:
    """Первый вход пользователя Keycloak: заводим локальную запись по sub."""
    roles = roles_from_claims(claims)
    role = "employer" if "employer" in roles else "admin" if "admin" in roles else "candidate"
    email = (claims.get("email") or claims.get("preferred_username") or claims["sub"]).lower()
    if not email_domain_allowed(email):
        raise Forbidden("Вход доступен только с почтой в домене %s" % allowed_tlds_text(), code="email_domain_not_allowed")
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        # учётная запись создана раньше локально — связываем по проверенному адресу
        if not claims.get("email_verified"):
            raise Unauthorized("Адрес почты в токене не подтверждён", code="email_not_verified")
        secure_unverified_account(db, existing, via="keycloak")
        existing.external_sub = claims["sub"]
        db.commit()
        return existing
    user = User(
        email=email,
        role=role,
        email_verified=bool(claims.get("email_verified")),
        external_sub=claims["sub"],
    )
    db.add(user)
    db.flush()
    if role == "candidate":
        db.add(CandidateProfile(user_id=user.id, contact_email=email))
    db.commit()
    return user


def get_current_user(
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Требуется вход в систему")
    claims = decode_access_token(credentials.credentials)
    if get_settings().auth_mode == "keycloak":
        user = db.scalar(select(User).where(User.external_sub == claims["sub"]))
        if user is None:
            user = _provision_external_user(db, claims)
        elif bool(claims.get("email_verified")) != user.email_verified:
            user.email_verified = bool(claims.get("email_verified"))
            db.commit()
    else:
        try:
            user = db.get(User, uuid.UUID(claims["sub"]))
        except ValueError:
            user = None
    if user is None or not user.is_active:
        raise Unauthorized("Пользователь не найден или отключён")
    return user


def require_role(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise Forbidden("Раздел доступен только для роли: " + ", ".join(roles), code="wrong_role")
        if get_settings().require_email_verification and not user.email_verified:
            raise Forbidden("Подтвердите адрес электронной почты", code="email_not_verified")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentCandidate = Annotated[User, Depends(require_role("candidate"))]
CurrentEmployer = Annotated[User, Depends(require_role("employer"))]
