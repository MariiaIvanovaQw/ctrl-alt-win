"""Связь профиля кандидата с ФСП ID."""

from urllib.parse import urlencode

from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import AppError, errors
from app.models import CandidateProfile, OidcState
from app.schemas import FspAchievementOut
from app.security.deps import DB, CurrentCandidate
from app.services import fsp

router = APIRouter(tags=["Кандидат: ФСП ID"])


class LinkIn(BaseModel):
    consent: bool = Field(description="Согласие на получение сведений из реестра ФСП")
    redirect_after: str | None = Field(
        None, max_length=255, pattern=r"^/([^/\\\s]\S*)?$",
        description="Куда вернуть пользователя после входа в ФСП ID: путь фронтенда, например /candidate/fsp",
    )


class LinkCompleteIn(BaseModel):
    code: str = Field(min_length=10, max_length=4096, description="Параметр fsp_code из адреса возврата")
    state: str = Field(min_length=10, max_length=64, description="Параметр fsp_state из адреса возврата")


class AuthorizationUrlOut(BaseModel):
    authorization_url: str


class FspStats(BaseModel):
    competitions: int
    wins: int
    podiums: int
    finals: int


class FspStatusOut(BaseModel):
    linked: bool
    fsp_id: str | None
    display_name: str | None
    region: str | None
    sport_rank: str | None
    sport_rank_title: str | None
    stats: FspStats
    linked_at: str | None
    last_sync_at: str | None
    sync_error: str | None
    score: float = Field(description="Вклад достижений в ранжирование, 0..1")
    achievements: list[FspAchievementOut]
    note: str | None


def _status(db, user) -> FspStatusOut:
    link = fsp.link_of(db, user.id)
    achievements = fsp.achievements_of(db, user.id)
    profile = db.get(CandidateProfile, user.id)
    spec = profile.primary_specialization if profile else None
    score = fsp.fsp_score(achievements, spec)
    return FspStatusOut(
        linked=link is not None,
        fsp_id=link.fsp_id if link else None,
        display_name=link.display_name if link else None,
        region=link.region if link else None,
        sport_rank=link.sport_rank if link else None,
        sport_rank_title=fsp.rank_title(link.sport_rank) if link else None,
        stats=score.get("stats") or fsp.fsp_stats(achievements),
        linked_at=fsp.iso(link.linked_at) if link else None,
        last_sync_at=fsp.iso(link.last_sync_at) if link else None,
        sync_error=link.sync_error if link else None,
        score=score["score"],
        achievements=[fsp.describe(a) for a in achievements],
        note=None
        if achievements
        else (
            "Достижений в реестре ФСП пока нет. Это не влияет на категорию и остальные показатели профиля."
            if link
            else "ФСП ID не привязан. Привязка добавит в профиль подтверждённые достижения соревнований."
        ),
    )


@router.get("/api/v1/candidate/fsp", response_model=FspStatusOut, summary="Статус привязки и достижения ФСП")
def status(user: CurrentCandidate, db: DB):
    return _status(db, user)


@router.post("/api/v1/candidate/fsp/link", response_model=AuthorizationUrlOut, responses=errors(400, 409, 503),
             summary="Начать привязку ФСП ID")
def start_link(body: LinkIn, user: CurrentCandidate, db: DB):
    """
    Возвращает адрес входа в ФСП ID (OpenID Connect, Authorization Code +
    PKCE). После входа ФСП ID возвращает браузер на фронтенд по пути
    `redirect_after` с параметрами `fsp=confirm&fsp_code=…&fsp_state=…`;
    фронтенд завершает привязку методом `POST /candidate/fsp/link/complete`.
    """
    url = fsp.start_link(db, user, body.consent, body.redirect_after)
    return {"authorization_url": url}


@router.post("/api/v1/candidate/fsp/link/complete", response_model=FspStatusOut, responses=errors(400, 403, 409, 502),
             summary="Завершить привязку ФСП ID")
def complete_link(body: LinkCompleteIn, user: CurrentCandidate, db: DB):
    """
    Завершает привязку от имени вошедшего кандидата: `state` должен
    принадлежать именно ему (`fsp_state_foreign` — привязку начал другой
    пользователь). Так чужая ссылка привязки не присоединит ФСП ID жертвы к
    профилю злоумышленника.
    """
    fsp.complete_link(db, user, body.code, body.state)
    return _status(db, user)


@router.post("/api/v1/candidate/fsp/sync", response_model=FspStatusOut, responses=errors(404),
             summary="Обновить достижения из реестра ФСП")
def sync(user: CurrentCandidate, db: DB):
    fsp.sync(db, user.id)
    db.commit()
    return _status(db, user)


@router.delete("/api/v1/candidate/fsp", status_code=204, responses=errors(404), summary="Отвязать ФСП ID")
def unlink(user: CurrentCandidate, db: DB):
    fsp.unlink(db, user)
    return Response(status_code=204)


@router.get(
    "/api/v1/fsp/link/callback",
    response_class=RedirectResponse,
    status_code=303,
    summary="Возврат из ФСП ID (redirect_uri)",
    tags=["Кандидат: ФСП ID"],
)
def callback(db: DB, code: str | None = None, state: str | None = None, error: str | None = None):
    """
    Вход через ФСП ID завершается здесь и передаёт фронтенду одноразовый код
    (`/login/fsp?code=…`). Привязка к уже вошедшему кандидату здесь не
    завершается: браузер уходит на фронтенд с `fsp_code` и `fsp_state`, и
    фронтенд вызывает `POST /candidate/fsp/link/complete` со своим токеном.
    """
    frontend = get_settings().frontend_url.rstrip("/")
    if state and fsp.is_login_state(db, state):
        # вход через ФСП ID: фронтенд получает одноразовый код и меняет его на токены
        if error or not code:
            return RedirectResponse(frontend + "/login?fsp=cancelled", status_code=303)
        try:
            login_code, redirect_after = fsp.complete_login(db, code, state)
        except AppError as exc:
            return RedirectResponse(frontend + "/login?" + urlencode({"fsp": "error", "reason": exc.code}), status_code=303)
        query = {"code": login_code}
        if redirect_after:
            query["next"] = redirect_after
        return RedirectResponse(frontend + "/login/fsp?" + urlencode(query), status_code=303)
    # привязка: возвращаем туда, откуда её начали
    pending = db.get(OidcState, state) if state else None
    back = frontend + ((pending.redirect_after if pending else None) or "/candidate/fsp")
    if error or not code or pending is None or pending.purpose != "link":
        if pending is not None and pending.purpose == "link":
            db.delete(pending)
            db.commit()
        return RedirectResponse(back + "?" + urlencode({"fsp": "cancelled" if error else "error"}), status_code=303)
    return RedirectResponse(back + "?" + urlencode({"fsp": "confirm", "fsp_code": code, "fsp_state": state}), status_code=303)
