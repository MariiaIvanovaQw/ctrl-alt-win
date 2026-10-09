"""Согласия пользователя на обработку и публикацию данных (152-ФЗ)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Consent

CONSENT_VERSION = "2026-10.2"

CONSENT_KINDS = {
    "pd_processing": "Согласие на обработку персональных данных для подбора вакансий",
    # не «обезличенный»: по достижениям ФСП (мероприятие, команда, место) человека можно узнать,
    # поэтому текст говорит прямо, что видно, и что ФСП можно скрыть
    "profile_publication": "Согласие на показ профиля работодателям платформы: без контактов и с инициалами вместо ФИО "
                           "(если не разрешено иное); видны категория, результаты теста, город, стек, ожидания по "
                           "зарплате и достижения ФСП — их и другие поля можно скрыть в настройках приватности",
    "fsp_data": "Согласие на получение сведений о достижениях из реестра ФСП",
}


def set_consent(db: Session, user_id: uuid.UUID, kind: str, granted: bool) -> Consent:
    consent = Consent(user_id=user_id, kind=kind, version=CONSENT_VERSION, granted=granted)
    db.add(consent)
    return consent


def current_consents(db: Session, user_id: uuid.UUID) -> dict[str, dict]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user_id).order_by(Consent.created_at)).all()
    state = {kind: {"kind": kind, "title": title, "granted": False, "version": None, "updated_at": None}
             for kind, title in CONSENT_KINDS.items()}
    for row in rows:
        if row.kind in state:
            state[row.kind].update(granted=row.granted, version=row.version, updated_at=row.created_at)
    return state


def has_consent(db: Session, user_id: uuid.UUID, kind: str) -> bool:
    row = db.scalar(
        select(Consent).where(Consent.user_id == user_id, Consent.kind == kind).order_by(Consent.created_at.desc())
    )
    return bool(row and row.granted)


def audit(db: Session, actor_id, action: str, target_type: str | None = None, target_id=None, **data) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            data=data,
        )
    )
