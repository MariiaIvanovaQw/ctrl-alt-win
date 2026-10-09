"""Публичная страница законного представителя: согласие по ссылке из письма."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.errors import errors
from app.security.deps import DB
from app.services import minors

router = APIRouter(prefix="/api/v1/guardian-consent", tags=["Законный представитель"])


class GuardianViewOut(BaseModel):
    candidate_name: str
    candidate_age: int | None
    guardian_name: str
    status: str = Field(description="pending | granted | declined | revoked")
    expires_at: datetime
    link_expired: bool
    what: list[str] = Field(description="На что соглашается представитель")
    link_closed: bool = Field(False, description="После отказа или отзыва ссылка больше не действует: нужен новый запрос кандидата")


class GuardianDecisionIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    decision: Literal["grant", "decline", "revoke"] = Field(
        description="grant — дать согласие; decline — отказать; revoke — отозвать данное ранее"
    )


@router.get("", response_model=GuardianViewOut, responses=errors(404), summary="Что подтверждает представитель")
def view(db: DB, token: str = Query(min_length=10, max_length=200)):
    """Имя и возраст кандидата, текущий статус и что означает согласие. Вход не нужен: доступ по ссылке из письма."""
    return minors.guardian_view(db, token)


@router.post("", response_model=GuardianViewOut, responses=errors(400, 404, 409), summary="Дать, не дать или отозвать согласие")
def decide(body: GuardianDecisionIn, db: DB):
    """
    Отзыв или отказ сразу скрывает профиль кандидата от работодателей, а
    ссылка перестаёт действовать: снова дать согласие можно только по
    новому запросу кандидата (`link_closed`).
    """
    return minors.guardian_decide(db, body.token, body.decision)
