"""
Модерация (роль admin): компании на проверке после жалоб кандидатов и
заявки на добровольную метку «Компания проверена».

Полноценная модерация с очередями и SLA — за рамками MVP; здесь минимум,
без которого автоматическая приостановка была бы необратимой.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.errors import NotFound, errors
from app.models import Company, Complaint, User
from app.security.deps import DB, require_role
from app.services import trust

router = APIRouter(prefix="/api/v1/admin", tags=["Модерация"], responses=errors(403))
CurrentAdmin = Annotated[User, Depends(require_role("admin"))]


class ReviewIn(BaseModel):
    decision: Literal["restore", "block"]
    comment: str | None = Field(None, max_length=1000)


class VerificationIn(BaseModel):
    approve: bool = Field(description="true — метка выдана, false — отказ")
    comment: str | None = Field(None, max_length=1000, description="Причина отказа: её увидит компания")


class ComplaintOut(BaseModel):
    id: str
    reason: str
    reason_title: str
    comment: str | None
    invitation_id: str | None
    vacancy_id: str | None
    created_at: datetime
    counted: bool = Field(description="Автор взаимодействовал с компанией: жалоба учитывается в автоматической приостановке")


class CompanyReviewOut(BaseModel):
    id: str
    name: str
    inn: str | None = None
    website: str | None = None
    verification_status: str = "none"
    verification_requested_at: datetime | None = None
    review_status: str
    review_reason: str | None
    reviewed_at: datetime | None
    complaints: int
    trust: dict


def _out(db, c: Company) -> CompanyReviewOut:
    return CompanyReviewOut(id=str(c.id), name=c.name, inn=c.inn, website=c.website,
                            verification_status=c.verification_status,
                            verification_requested_at=c.verification_requested_at,
                            review_status=c.review_status, review_reason=c.review_reason,
                            reviewed_at=c.reviewed_at, complaints=c.complaints, trust=trust.company_trust(db, c))


@router.get("/companies", response_model=list[CompanyReviewOut], summary="Компании по статусу проверки")
def companies(user: CurrentAdmin, db: DB, status: str = Query("on_review", pattern="^(active|on_review|blocked)$")):
    return [_out(db, c) for c in db.scalars(select(Company).where(Company.review_status == status).order_by(Company.name))]


@router.get("/companies/{company_id}/complaints", response_model=list[ComplaintOut], summary="Жалобы на компанию")
def complaints(company_id: uuid.UUID, user: CurrentAdmin, db: DB):
    rows = db.scalars(select(Complaint).where(Complaint.company_id == company_id).order_by(Complaint.created_at.desc()))
    interacted = trust.interacted_candidates(db, company_id)
    return [
        ComplaintOut(id=str(c.id), reason=c.reason, reason_title=trust.COMPLAINT_REASONS.get(c.reason, c.reason),
                     comment=c.comment, invitation_id=str(c.invitation_id) if c.invitation_id else None,
                     vacancy_id=str(c.need_id) if c.need_id else None, created_at=c.created_at,
                     counted=c.reporter_user_id in interacted)
        for c in rows
    ]


@router.post("/companies/{company_id}/review", response_model=CompanyReviewOut, responses=errors(404), summary="Решение по компании")
def review(company_id: uuid.UUID, body: ReviewIn, user: CurrentAdmin, db: DB):
    """restore — вернуть компании доступ; block — заблокировать."""
    company = db.get(Company, company_id)
    if company is None:
        raise NotFound("Компания не найдена")
    return _out(db, trust.review(db, user, company, body.decision, body.comment))


@router.get("/verification-requests", response_model=list[CompanyReviewOut], summary="Заявки на метку «Компания проверена»")
def verification_requests(user: CurrentAdmin, db: DB):
    """Сверка ИНН и названия с ЕГРЮЛ выполняется модератором вручную (автоматическая — после MVP)."""
    rows = db.scalars(
        select(Company).where(Company.verification_status == "requested").order_by(Company.verification_requested_at)
    )
    return [_out(db, c) for c in rows]


@router.post("/companies/{company_id}/verification", response_model=CompanyReviewOut, responses=errors(404, 409),
             summary="Решение по заявке на проверку")
def decide_verification(company_id: uuid.UUID, body: VerificationIn, user: CurrentAdmin, db: DB):
    company = db.get(Company, company_id)
    if company is None:
        raise NotFound("Компания не найдена")
    return _out(db, trust.decide_verification(db, user, company, body.approve, body.comment))
