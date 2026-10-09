"""Интеграция с ATS работодателя: вебхуки о событиях и выгрузка кандидата (JSON Resume)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.employer import company_of, data_company
from app.errors import AppError, NotFound, errors
from app.models import User, WebhookDelivery, WebhookEndpoint
from app.security.deps import DB, CurrentEmployer
from app.services import webhooks
from app.services.consents import audit
from app.services.export import candidate_json_resume

router = APIRouter(prefix="/api/v1/employer", tags=["Работодатель: интеграции (ATS)"], responses=errors(403))


class EventOut(BaseModel):
    event: str
    title: str


class JsonResumeOut(BaseModel):
    """JSON Resume (jsonresume.org) с расширением x-talent — подтверждённые платформой сведения."""

    model_config = ConfigDict(populate_by_name=True)

    schema_url: str = Field(alias="$schema")
    basics: dict
    skills: list[dict]
    languages: list[dict]
    meta: dict
    x_talent: dict = Field(alias="x-talent")


def check_events(events: list[str] | None) -> list[str] | None:
    if events is None:
        return None
    unknown = [e for e in events if e not in webhooks.EVENTS]
    if unknown:
        raise ValueError("неизвестные события: " + ", ".join(unknown))
    return list(dict.fromkeys(events))


class WebhookIn(BaseModel):
    url: str = Field(max_length=500, description="Адрес ATS, https; во внутреннюю сеть нельзя (кроме явной настройки для разработки)")
    events: list[str] = Field(min_length=1, description="События из GET /employer/webhooks/events")
    description: str | None = Field(None, max_length=200)

    @field_validator("events")
    @classmethod
    def _events(cls, v):
        return check_events(v)


class WebhookPatch(BaseModel):
    url: str | None = Field(None, max_length=500)
    events: list[str] | None = None
    description: str | None = Field(None, max_length=200)
    active: bool | None = None

    @field_validator("events")
    @classmethod
    def _events(cls, v):
        return check_events(v)


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    description: str | None
    active: bool
    created_at: datetime
    last_success_at: datetime | None
    last_error: str | None
    secret: str | None = Field(None, description="Секрет подписи — показывается только при создании")
    secret_hint: str


class DeliveryOut(BaseModel):
    id: str
    event: str
    status: str
    attempts: int
    response_code: int | None
    last_error: str | None
    created_at: datetime
    next_attempt_at: datetime
    delivered_at: datetime | None
    payload: dict


def _out(e: WebhookEndpoint, with_secret: bool = False) -> WebhookOut:
    return WebhookOut(
        id=str(e.id), url=e.url, events=e.events or [], description=e.description, active=e.active,
        created_at=e.created_at, last_success_at=e.last_success_at, last_error=e.last_error,
        secret=e.secret if with_secret else None, secret_hint=e.secret[:10] + "…",
    )


def _delivery_out(d: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=str(d.id), event=d.event, status=d.status, attempts=d.attempts, response_code=d.response_code,
        last_error=d.last_error, created_at=d.created_at, next_attempt_at=d.next_attempt_at,
        delivered_at=d.delivered_at, payload=d.payload,
    )


def _own_endpoint(db, company, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.company_id != company.id:
        raise NotFound("Вебхук не найден")
    return endpoint


@router.get("/webhooks/events", response_model=list[EventOut], summary="События, на которые можно подписаться")
def events():
    return [{"event": k, "title": v} for k, v in webhooks.EVENTS.items()]


@router.get("/webhooks", response_model=list[WebhookOut], summary="Подписки ATS на события")
def list_webhooks(user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    return [_out(e) for e in db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.company_id == company.id))]


@router.post("/webhooks", response_model=WebhookOut, status_code=201, responses=errors(400, 404),
             summary="Подписать адрес ATS на события")
def create_webhook(body: WebhookIn, user: CurrentEmployer, db: DB):
    """
    Каждое событие приходит POST-запросом с JSON
    `{"id", "event", "created_at", "company_id", "data"}` и заголовками
    `X-Talent-Event`, `X-Talent-Delivery`, `X-Talent-Timestamp`,
    `X-Talent-Signature: sha256=HMAC-SHA256(secret, "<timestamp>.<тело>")`.
    Секрет возвращается только в этом ответе.
    """
    company = company_of(db, user)
    endpoint = WebhookEndpoint(company_id=company.id, url=webhooks.validate_url(body.url), secret=webhooks.new_secret(),
                               events=body.events, description=body.description)
    db.add(endpoint)
    audit(db, user.id, "webhook.created", "company", company.id, url=body.url)
    db.commit()
    return _out(endpoint, with_secret=True)


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookOut, responses=errors(400, 404), summary="Изменить подписку")
def update_webhook(endpoint_id: uuid.UUID, body: WebhookPatch, user: CurrentEmployer, db: DB):
    endpoint = _own_endpoint(db, company_of(db, user), endpoint_id)
    data = body.model_dump(exclude_unset=True)
    if "url" in data:
        data["url"] = webhooks.validate_url(data["url"])
    if data.get("events") == []:
        raise AppError("Нужно хотя бы одно событие", code="events_required")
    for field, value in data.items():
        setattr(endpoint, field, value)
    db.commit()
    return _out(endpoint)


@router.delete("/webhooks/{endpoint_id}", status_code=204, responses=errors(404), summary="Удалить подписку")
def delete_webhook(endpoint_id: uuid.UUID, user: CurrentEmployer, db: DB):
    endpoint = _own_endpoint(db, company_of(db, user), endpoint_id)
    db.delete(endpoint)
    db.commit()
    return Response(status_code=204)


@router.post("/webhooks/{endpoint_id}/rotate-secret", response_model=WebhookOut, responses=errors(404), summary="Выпустить новый секрет")
def rotate_secret(endpoint_id: uuid.UUID, user: CurrentEmployer, db: DB):
    endpoint = _own_endpoint(db, company_of(db, user), endpoint_id)
    endpoint.secret = webhooks.new_secret()
    db.commit()
    return _out(endpoint, with_secret=True)


@router.post("/webhooks/{endpoint_id}/ping", response_model=DeliveryOut, responses=errors(404), summary="Отправить проверочное событие")
def ping(endpoint_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    endpoint = _own_endpoint(db, company, endpoint_id)
    delivery = WebhookDelivery(endpoint_id=endpoint.id, event=webhooks.PING,
                               payload={"event": webhooks.PING, "company_id": str(company.id), "data": {"message": "pong"}})
    db.add(delivery)
    db.flush()
    delivery.payload = dict(delivery.payload, id=str(delivery.id))
    with webhooks._client() as client:
        webhooks.deliver(db, delivery, client)
    db.commit()
    return _delivery_out(delivery)


@router.get("/webhooks/{endpoint_id}/deliveries", response_model=list[DeliveryOut], responses=errors(404), summary="Журнал доставок")
def deliveries(endpoint_id: uuid.UUID, user: CurrentEmployer, db: DB, status: str | None = Query(None),
               limit: int = Query(50, ge=1, le=200)):
    endpoint = _own_endpoint(db, company_of(db, user), endpoint_id)
    query = select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
    if status:
        query = query.where(WebhookDelivery.status == status)
    return [_delivery_out(d) for d in db.scalars(query.order_by(WebhookDelivery.created_at.desc()).limit(limit))]


@router.post("/webhooks/deliveries/{delivery_id}/retry", response_model=DeliveryOut, responses=errors(404), summary="Повторить доставку")
def retry_delivery(delivery_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None or db.get(WebhookEndpoint, delivery.endpoint_id).company_id != company.id:
        raise NotFound("Доставка не найдена")
    return _delivery_out(webhooks.retry(db, delivery))


@router.get("/candidates/{public_id}/export", response_model=JsonResumeOut, responses=errors(404),
            summary="Выгрузка кандидата для ATS (JSON Resume)")
def export_candidate(public_id: str, user: CurrentEmployer, db: DB):
    """
    Формат JSON Resume; подтверждённые платформой сведения — в `x-talent`.
    Контакты и полное имя есть, только если кандидат принял приглашение
    компании или откликнулся на её вакансию.
    """
    company = data_company(db, user)
    candidate = db.scalar(select(User).where(User.public_id == public_id, User.role == "candidate", User.is_active.is_(True)))
    if candidate is None:
        raise NotFound("Кандидат не найден")
    return candidate_json_resume(db, company.id, candidate)
