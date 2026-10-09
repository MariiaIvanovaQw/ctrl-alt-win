"""
Служебные эндпоинты.

* /idp/realms/platform/... — discovery и JWKS локального провайдера в
  формате Keycloak: другие сервисы проверяют токены платформы так же, как
  токены Keycloak.
* /api/v1/dev/... — только в демо-режиме (APP_DEMO_MODE=true): ссылка
  подтверждения почты, демо-учётные записи без модератора, экспресс-режим
  и сброс попыток теста для жюри. В эксплуатации этих методов нет (404).
"""

import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import utcnow
from app.errors import Conflict, NotFound, errors
from app.models import (
    Attempt,
    AttemptAnswer,
    CandidateGrade,
    CompetencyEstimate,
    GradeHistory,
    GradeRecommendation,
    OutboxEmail,
)
from app.security.deps import DB, CurrentCandidate
from app.security.tokens import jwks
from app.services import assessment
from app.services.consents import audit
from app.services.simulation import simulated_answers

router = APIRouter(tags=["Служебное"])


@router.get("/idp/realms/platform/.well-known/openid-configuration", response_model=dict,
            summary="OIDC discovery локального провайдера")
def discovery():
    settings = get_settings()
    base = settings.local_issuer
    return {
        "issuer": base,
        "jwks_uri": base + "/protocol/openid-connect/certs",
        "token_endpoint": settings.public_base_url.rstrip("/") + "/api/v1/auth/login",
        "id_token_signing_alg_values_supported": ["RS256"],
        "claims_supported": ["sub", "email", "email_verified", "preferred_username", "realm_access"],
    }


@router.get("/idp/realms/platform/protocol/openid-connect/certs", response_model=dict, summary="JWKS локального провайдера")
def certs():
    return jwks()


def _dev_only() -> None:
    if not get_settings().demo_mode:
        raise NotFound("Not Found")


class MailOut(BaseModel):
    to: str
    subject: str
    body: str
    created_at: datetime
    sent_at: datetime | None


@router.get("/api/v1/dev/mailbox", response_model=list[MailOut], responses=errors(404),
            summary="Письмо подтверждения адреса (только демо-режим)")
def mailbox(db: DB, to: EmailStr = Query(description="Адрес, указанный при регистрации")):
    """
    Подтверждение почты на демонстрации не обязательно (уточнение
    постановщиков), поэтому демо-стенд показывает ссылку из письма. Отдаются
    только письма подтверждения адреса на указанный адрес за сутки — без
    чужих уведомлений, ссылок законному представителю и восстановления
    пароля. Новый фронтенд берёт ссылку из ответа регистрации
    (`dev_verification_link`); метод оставлен для совместимости.
    """
    _dev_only()
    query = (
        select(OutboxEmail)
        .where(
            func.lower(OutboxEmail.to_email) == to.lower(),
            OutboxEmail.kind == "verify_email",
            OutboxEmail.created_at >= utcnow() - timedelta(days=1),
        )
        .order_by(OutboxEmail.created_at.desc())
        .limit(5)
    )
    return [
        MailOut(to=m.to_email, subject=m.subject, body=m.body, created_at=m.created_at, sent_at=m.sent_at)
        for m in db.scalars(query)
    ]


class ResetOut(BaseModel):
    message: str


class AutofillOut(BaseModel):
    attempt_id: uuid.UUID
    filled: int
    outcome: str | None
    score: int | None


@router.post("/api/v1/dev/me/reset-assessment", response_model=ResetOut, responses=errors(404),
             summary="Сбросить свои попытки и грейды (только демо)")
def reset_my_assessment(user: CurrentCandidate, db: DB):
    """
    Для проверки жюри: убирает попытки, грейды, рекомендации и оценки
    компетенций текущего кандидата, чтобы пройти тест заново без ожидания
    и проверить воспроизводимость. Опрос сохраняется. В эксплуатации
    (без APP_DEMO_MODE) метода нет.
    """
    _dev_only()
    for model in (GradeRecommendation, GradeHistory, CandidateGrade, CompetencyEstimate):
        db.execute(delete(model).where(model.user_id == user.id))
    db.execute(delete(Attempt).where(Attempt.user_id == user.id))
    audit(db, user.id, "dev.assessment_reset", "user", user.id)
    db.commit()
    return {"message": "Попытки и грейды сброшены: тест можно пройти заново"}


# Профиль симулятора банка для каждого варианта «ответить как…»
AUTOFILL_PROFILES = {
    "junior": "solid_junior",
    "middle": "solid_middle",
    "senior": "solid_senior",
    "guesser": "guesser",
}


class AutofillIn(BaseModel):
    answer_as: Literal["junior", "middle", "senior", "guesser"] = Field(
        description="Чьи ответы подставить в оставшиеся задания: типичного кандидата уровня "
                    "junior / middle / senior или угадывающего наугад (guesser)",
    )


@router.post(
    "/api/v1/dev/me/attempts/{attempt_id}/autofill",
    response_model=AutofillOut,
    responses=errors(404, 409),
    summary="Экспресс-режим: дозаполнить и завершить попытку (только демо)",
)
def autofill_attempt(attempt_id: uuid.UUID, body: AutofillIn, user: CurrentCandidate, db: DB):
    """
    Для жюри: полный тест — 26 заданий и до 60 минут. Чтобы проверить
    механику за 3–5 минут, можно ответить на несколько заданий самому,
    а остальные заполнить ответами синтетического кандидата выбранного
    уровня (та же модель, что в процедуре валидации). Уже данные ответы не
    меняются; попытка сразу завершается и проходит обычный расчёт грейда
    со всеми правилами (кулдауны, пропуск на повышение, рекомендации).
    Попытка помечается признаком `demo_autofill`. В эксплуатации
    (без APP_DEMO_MODE) метода нет.
    """
    _dev_only()
    attempt = assessment.get_owned_attempt(db, user, attempt_id)
    if attempt.status != "in_progress":
        raise Conflict("Попытка уже завершена", code="attempt_finished")
    rows = [
        row for row in db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
        if row.submitted is None
    ]
    keys = [attempt.keys[row.position] for row in rows]
    values = simulated_answers(random.Random(attempt.seed), AUTOFILL_PROFILES[body.answer_as], keys)
    now = utcnow()
    for row in rows:
        row.submitted = {"value": values[row.item_id]}
        row.answered_at = now
    db.flush()
    attempt = assessment.finish_attempt(db, attempt, "demo_autofill")
    audit(db, user.id, "dev.attempt_autofill", "attempt", attempt.id, answer_as=body.answer_as, filled=len(rows))
    db.commit()
    return {"attempt_id": attempt.id, "filled": len(rows), "outcome": attempt.outcome, "score": attempt.score}


class DemoAccountsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    password: str | None = Field(None, description="Общий пароль демо-кандидатов, работодателей и жюри")
    candidates: list[dict] = Field(default_factory=list)
    employers: list[dict] = Field(default_factory=list)
    jury: list[dict] = Field(default_factory=list)
    moderator: dict | None = Field(None, description="Только адрес: пароль модератора в data/demo_accounts.json на сервере")
    note: str | None = None


@router.get("/api/v1/dev/demo-accounts", response_model=DemoAccountsOut, responses=errors(404),
            summary="Демо-учётные записи (только демо-режим)")
def demo_accounts():
    """
    Общий пароль подходит кандидатам, работодателям и жюри. У модератора
    свой пароль: он не отдаётся по сети и лежит в data/demo_accounts.json
    на сервере (тот, кто поднял стенд, видит его в файле).
    """
    _dev_only()
    path = get_settings().data_dir / "demo_accounts.json"
    if not path.exists():
        return DemoAccountsOut(note="Запустите python -m scripts.seed_demo")
    data = json.loads(path.read_text(encoding="utf-8"))
    moderator = data.get("moderator") or None
    if moderator:
        moderator = {k: v for k, v in moderator.items() if k != "password"}
        moderator["note"] = (moderator.get("note", "") + " Пароль модератора — в data/demo_accounts.json на сервере").strip()
    return DemoAccountsOut(**{**data, "moderator": moderator})
