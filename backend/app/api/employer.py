"""Кабинет работодателя: компания, потребности, подборки и поиск кандидатов."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import utcnow
from app.errors import AppError, Forbidden, NotFound, errors
from app.models import Company, EmployerTask, Invitation, Message, Need, RefreshToken, Selection, User, WebhookEndpoint
from app.reference import INDUSTRIES
from app.schemas import CandidateCard, Level, SalaryRange, SearchOut, SelectionOut, Specialization, check_skills
from app.security.deps import DB, CurrentEmployer
from app.services import matching, trust
from app.services.cards import build_card, contacts_access, log_contact_view
from app.services.consents import audit, has_consent
from app.services.mailer import forget_recipient
from app.services.needs import build_need_profile, test_coverage
from app.services.pdf import render_profile
from app.services.search import (
    SearchFilters,
    get_selection,
    need_profile,
    run_selection,
    search_bank,
    selection_chain,
    selection_rows,
)

router = APIRouter(prefix="/api/v1/employer", tags=["Работодатель: подбор"], responses=errors(403))


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    inn: str | None = Field(None, pattern=r"^\d{10}(\d{2})?$", description="ИНН (10 или 12 цифр)")
    industry: str | None = None
    description: str | None = Field(None, max_length=5000)
    website: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(None, max_length=40)

    @field_validator("industry")
    @classmethod
    def _industry(cls, v):
        if v is not None and v not in INDUSTRIES:
            raise ValueError("неизвестная отрасль")
        return v


class CompanyOut(CompanyIn):
    id: str
    verified: bool = Field(description="Добровольная метка «Компания проверена» (модератор сверил ИНН с ЕГРЮЛ)")
    verification_status: str = Field("none", description="none | requested | verified | rejected")
    verification_title: str = ""
    verification_comment: str | None = None
    review_status: str = Field(description="active | on_review (после жалоб кандидатов) | blocked")
    review_reason: str | None = None
    complaints: int = 0
    created_at: datetime


class NeedIn(SalaryRange):
    title: str = Field(min_length=3, max_length=200)
    specialization: Specialization
    level: Level
    description: str = Field("", max_length=10000, description="Чем занимается команда, какие задачи")
    team_description: str | None = Field(None, max_length=3000)
    stack: list[str] = Field(default_factory=list)
    work_format: str = Field("any", pattern="^(any|office|hybrid|remote)$")
    city: str | None = Field(None, max_length=100)
    suitable_for_minors: bool = Field(False, description="Подходит для несовершеннолетних кандидатов (15–17 лет): лёгкий труд, сокращённое рабочее время, без вредных и опасных условий (ст. 63, 92, 265 ТК РФ)")

    @field_validator("stack")
    @classmethod
    def _stack(cls, v):
        return check_skills(v)


class NeedUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    specialization: Specialization | None = None
    level: Level | None = None
    description: str | None = Field(None, max_length=10000)
    team_description: str | None = Field(None, max_length=3000)
    stack: list[str] | None = None
    work_format: str | None = Field(None, pattern="^(any|office|hybrid|remote)$")
    city: str | None = Field(None, max_length=100)
    salary_from: int | None = Field(None, gt=0)
    salary_to: int | None = Field(None, gt=0)
    suitable_for_minors: bool | None = None

    @field_validator("stack")
    @classmethod
    def _stack(cls, v):
        return check_skills(v)


class NeedOut(BaseModel):
    id: str
    title: str
    specialization: str
    level: str
    description: str
    team_description: str | None
    stack: list[str]
    work_format: str
    city: str | None
    salary_from: int
    salary_to: int
    is_published: bool
    status: str
    suitable_for_minors: bool = False
    profile: dict = Field(description="Профиль потребности: веса компетенций, навыки, источник весов")
    created_at: datetime
    published_at: datetime | None


class NeedProfileOut(BaseModel):
    competency_weights: dict[str, float]
    top_competencies: list[dict]
    skills: list[str]
    skills_from_text: list[str]
    role_profile: str


class CoverageOut(BaseModel):
    seeds_simulated: int
    competencies: list[dict] = Field(description="competency, title, weight, mandatory_in_test, share_of_attempts, items_per_attempt")


class NeedTestPreviewOut(BaseModel):
    need_id: str
    category: dict
    profile: NeedProfileOut
    coverage: CoverageOut


class SelectionListItem(BaseModel):
    id: str
    parent_id: str | None
    params: dict
    total: int | None
    created_at: datetime


class CategoryStatOut(BaseModel):
    specialization: str
    specialization_title: str
    level: str
    title: str
    candidates: int = Field(description="С грейдом, подтверждённым тестом")
    unconfirmed: int = Field(description="Заявили этот уровень, но не подтвердили тестом")
    with_fsp_achievements: int
    avg_profile_strength: float | None


def company_of(db, user: User) -> Company:
    company = db.scalar(select(Company).where(Company.owner_user_id == user.id))
    if company is None:
        raise NotFound("Сначала заполните профиль компании", code="company_required")
    return company


def data_company(db, user: User) -> Company:
    """Компания, которой открыты данные кандидатов: не заблокирована модератором."""
    company = company_of(db, user)
    trust.ensure_not_blocked(company)
    return company


def _company_out(c: Company) -> CompanyOut:
    return CompanyOut(
        id=str(c.id), name=c.name, inn=c.inn, industry=c.industry, description=c.description, website=c.website,
        city=c.city, contact_email=c.contact_email, contact_phone=c.contact_phone, verified=c.verified,
        verification_status=c.verification_status, verification_title=trust.VERIFICATION_TITLES[c.verification_status],
        verification_comment=c.verification_comment, review_status=c.review_status, review_reason=c.review_reason, complaints=c.complaints, created_at=c.created_at,
    )


def _need_out(n: Need) -> NeedOut:
    return NeedOut(
        id=str(n.id), title=n.title, specialization=n.specialization, level=n.level, description=n.description,
        team_description=n.team_description, stack=n.stack or [], work_format=n.work_format, city=n.city,
        salary_from=n.salary_from, salary_to=n.salary_to, is_published=n.is_published, status=n.status,
        suitable_for_minors=bool(n.suitable_for_minors),
        profile=n.profile or {}, created_at=n.created_at, published_at=n.published_at,
    )


def _own_need(db, company: Company, need_id: uuid.UUID) -> Need:
    need = db.get(Need, need_id)
    if need is None or need.company_id != company.id:
        raise NotFound("Потребность не найдена")
    return need


def _selection_out(db, company: Company, s: Selection) -> SelectionOut:
    rows, unavailable = selection_rows(db, company, s)
    return SelectionOut(
        id=str(s.id), need_id=str(s.need_id) if s.need_id else None, parent_id=str(s.parent_id) if s.parent_id else None,
        params=s.params, summary=s.summary, results=rows, created_at=s.created_at, chain=selection_chain(db, s),
        unavailable=unavailable,
    )


# ------------------------------------------------------------------ компания


@router.get("/company", response_model=CompanyOut, responses=errors(404), summary="Профиль компании")
def get_company(user: CurrentEmployer, db: DB):
    return _company_out(company_of(db, user))


@router.put("/company", response_model=CompanyOut, summary="Создать или изменить профиль компании")
def put_company(body: CompanyIn, user: CurrentEmployer, db: DB):
    company = db.scalar(select(Company).where(Company.owner_user_id == user.id))
    if company is None:
        db.add(Company(owner_user_id=user.id, **body.model_dump()))
        try:
            db.commit()
            return _company_out(db.scalar(select(Company).where(Company.owner_user_id == user.id)))
        except IntegrityError:  # компанию одновременно создал параллельный запрос — обновляем её
            db.rollback()
            company = db.scalar(select(Company).where(Company.owner_user_id == user.id))
    old_name, old_inn = company.name, company.inn
    for field, value in body.model_dump().items():
        setattr(company, field, value)
    trust.on_company_edited(company, old_name, old_inn)
    db.commit()
    return _company_out(company)


@router.post("/company/verification", response_model=CompanyOut, responses=errors(400, 404, 409), summary="Запросить метку «Компания проверена»")
def request_verification(user: CurrentEmployer, db: DB):
    """
    Добровольная проверка: модератор сверяет ИНН и название с ЕГРЮЛ.
    Метка видна кандидатам рядом с приглашением; без неё компания работает
    как обычно. Нужен ИНН с верной контрольной суммой (`inn_invalid`).
    """
    return _company_out(trust.request_verification(db, user, company_of(db, user)))


# ------------------------------------------------------------------ потребности


@router.post("/needs", response_model=NeedOut, status_code=201, responses=errors(404), summary="Описать потребность")
def create_need(body: NeedIn, user: CurrentEmployer, db: DB):
    """
    Специализация, грейд, стек и описание команды. Из них строится профиль
    потребности: веса компетенций банка, по которым ранжируется подборка.
    Вилка зарплаты обязательна.
    """
    company = company_of(db, user)
    need = Need(company_id=company.id, **body.model_dump())
    need.profile = build_need_profile(need.specialization, need.level, need.stack, need.description, need.team_description)
    db.add(need)
    db.commit()
    return _need_out(need)


@router.get("/needs", response_model=list[NeedOut], summary="Мои потребности и вакансии")
def list_needs(user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    return [_need_out(n) for n in db.scalars(select(Need).where(Need.company_id == company.id).order_by(Need.created_at.desc()))]


@router.get("/needs/{need_id}", response_model=NeedOut, responses=errors(404), summary="Потребность")
def get_need(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    return _need_out(_own_need(db, company_of(db, user), need_id))


@router.patch("/needs/{need_id}", response_model=NeedOut, responses=errors(400, 404), summary="Изменить потребность")
def update_need(need_id: uuid.UUID, body: NeedUpdate, user: CurrentEmployer, db: DB):
    need = _own_need(db, company_of(db, user), need_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        # null у обязательных полей означает «не менять», а не «стереть»
        if value is None and field not in ("team_description", "city"):
            continue
        setattr(need, field, value)
    if need.salary_from > need.salary_to:
        raise AppError("Нижняя граница зарплаты больше верхней", code="invalid_salary")
    need.profile = build_need_profile(need.specialization, need.level, need.stack or [], need.description, need.team_description)
    db.commit()
    return _need_out(need)


@router.post("/needs/{need_id}/publish", response_model=NeedOut, responses=errors(404), summary="Опубликовать как вакансию")
def publish(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    trust.ensure_active(company)
    need = _own_need(db, company, need_id)
    need.is_published, need.status = True, "open"
    need.published_at = need.published_at or utcnow()
    db.commit()
    return _need_out(need)


@router.post("/needs/{need_id}/unpublish", response_model=NeedOut, responses=errors(404), summary="Снять с публикации")
def unpublish(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    need = _own_need(db, company_of(db, user), need_id)
    need.is_published = False
    db.commit()
    return _need_out(need)


@router.post("/needs/{need_id}/close", response_model=NeedOut, responses=errors(404), summary="Закрыть потребность")
def close(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    need = _own_need(db, company_of(db, user), need_id)
    need.status, need.is_published = "closed", False
    db.commit()
    return _need_out(need)


@router.get("/needs/{need_id}/test-preview", response_model=NeedTestPreviewOut, responses=errors(404),
            summary="Как тест категории проверяет эту потребность")
def need_test_preview(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    """
    Тест один для всей категории — иначе результаты кандидатов несопоставимы.
    Здесь видно, какие компетенции потребности измеряются в каждой попытке,
    а какие — в части попыток (по 20 смоделированным сидам).
    """
    need = _own_need(db, company_of(db, user), need_id)
    profile = need_profile(need)
    db.commit()
    return {
        "need_id": str(need.id),
        "category": {"specialization": need.specialization, "level": need.level},
        "profile": profile,
        "coverage": test_coverage(need.specialization, need.level, profile["competency_weights"]),
    }


# ------------------------------------------------------------------ подборки


@router.post("/needs/{need_id}/selections", response_model=SelectionOut, status_code=201, responses=errors(404),
             summary="Подобрать кандидатов под потребность")
def create_selection(need_id: uuid.UUID, body: SearchFilters, user: CurrentEmployer, db: DB):
    """
    Подборка из рекомендованных категорий (основная, «с запасом», «на вырост»),
    ранжированная по соответствию потребности, с обоснованием каждого места.
    Сохраняется и не теряется при уточнении.
    """
    company = data_company(db, user)
    need = _own_need(db, company, need_id)
    return _selection_out(db, company, run_selection(db, company, need, body))


@router.get("/needs/{need_id}/selections", response_model=list[SelectionListItem], responses=errors(404),
            summary="История подборок по потребности")
def list_selections(need_id: uuid.UUID, user: CurrentEmployer, db: DB):
    company = company_of(db, user)
    need = _own_need(db, company, need_id)
    rows = db.scalars(select(Selection).where(Selection.need_id == need.id).order_by(Selection.created_at.desc()))
    return [{"id": str(s.id), "parent_id": str(s.parent_id) if s.parent_id else None, "params": s.params,
             "total": s.summary.get("total_matched"), "created_at": s.created_at} for s in rows]


@router.get("/selections/{selection_id}", response_model=SelectionOut, responses=errors(404), summary="Подборка")
def get_selection_endpoint(selection_id: uuid.UUID, user: CurrentEmployer, db: DB):
    """Порядок и обоснования — как при создании; карточки и контакты — по текущим правам доступа."""
    company = data_company(db, user)
    return _selection_out(db, company, get_selection(db, company, selection_id))


@router.post("/selections/{selection_id}/refine", response_model=SelectionOut, status_code=201, responses=errors(400, 404),
             summary="Уточнить подборку")
def refine(selection_id: uuid.UUID, body: SearchFilters, user: CurrentEmployer, db: DB):
    """Создаёт новую подборку с новыми фильтрами; исходная остаётся доступной по своему id."""
    company = data_company(db, user)
    parent = get_selection(db, company, selection_id)
    if parent.need_id is None:
        raise AppError("Уточнять можно подборку по потребности", code="not_refinable")
    need = _own_need(db, company, parent.need_id)
    merged = SearchFilters(**{**parent.params, **body.model_dump(exclude_unset=True)})
    return _selection_out(db, company, run_selection(db, company, need, merged, parent=parent))


# ------------------------------------------------------------------ категории и поиск


@router.get("/categories", response_model=list[CategoryStatOut], summary="Категории кандидатов: численность и сила профилей")
def categories(user: CurrentEmployer, db: DB, specialization: Specialization | None = Query(None)):
    data_company(db, user)
    return matching.category_stats(db, specialization)


@router.get("/categories/{specialization}/{level}/candidates", response_model=SearchOut, summary="Кандидаты категории")
def category_candidates(
    specialization: Specialization,
    level: Level,
    user: CurrentEmployer,
    db: DB,
    has_fsp: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Внутри категории выше те, у кого сильнее подтверждённый профиль: тест, ФСП, свежесть."""
    company = data_company(db, user)
    return search_bank(db, company, SearchFilters(specialization=specialization, levels=[level], has_fsp=has_fsp, limit=limit))


@router.post("/candidates/search", response_model=SearchOut, summary="Поиск по банку кандидатов")
def search(body: SearchFilters, user: CurrentEmployer, db: DB):
    """
    Фильтры: специализация, грейды, стек, наличие достижений ФСП, город,
    формат, ожидания, текст. Фильтры видят только то, что кандидат
    показывает работодателям.
    """
    return search_bank(db, data_company(db, user), body)


def _card(db, user, public_id: str, full: bool = True, specialization: str | None = None):
    company = data_company(db, user)
    candidate = db.scalar(select(User).where(User.public_id == public_id, User.role == "candidate", User.is_active.is_(True)))
    if candidate is None or not has_consent(db, candidate.id, "profile_publication"):
        raise NotFound("Кандидат не найден")
    facts = matching.load_facts(db, user_ids=[candidate.id])
    if not facts:
        raise NotFound("Кандидат не найден")
    # направление, в котором работодатель нашёл кандидата, иначе основное; затем подтверждённый грейд
    primary = specialization or facts[0].profile.primary_specialization
    chosen = sorted(facts, key=lambda f: (f.grade.specialization != primary, not matching.is_confirmed(f.grade)))[0]
    reason = contacts_access(db, company.id, candidate.id)
    if reason:
        log_contact_view(db, user.id, candidate.id, reason)
        db.commit()
    card = build_card(chosen, contacts_reason=reason, full=full)
    # у кандидата может быть несколько категорий — по одной на направление
    card["other_categories"] = [build_card(f, full=False)["category"] for f in facts
                                if f.grade.specialization != chosen.grade.specialization]
    return facts, card, company


@router.get("/candidates/{public_id}", response_model=CandidateCard, responses=errors(404), summary="Карточка кандидата")
def candidate_card(public_id: str, user: CurrentEmployer, db: DB,
                   specialization: Specialization | None = Query(None, description="Направление, в котором нашли кандидата")):
    """
    Контакты видны, только если кандидат принял приглашение компании или откликнулся на её вакансию.
    Если у кандидата несколько категорий, карточка показывает категорию направления `specialization`
    (или основного), остальные перечислены в `other_categories`.
    """
    _facts, card, _company = _card(db, user, public_id, specialization=specialization)
    return card


@router.get(
    "/candidates/{public_id}/pdf",
    summary="PDF-профиль кандидата",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "PDF-файл"}, **errors(404)},
)
def candidate_pdf(public_id: str, user: CurrentEmployer, db: DB, specialization: Specialization | None = Query(None)):
    _facts, card, company = _card(db, user, public_id, specialization=specialization)
    pdf = render_profile(card, generated_for=company.name)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=candidate-%s.pdf" % public_id})


@router.get("/skills/extract", response_model=NeedProfileOut, summary="Разобрать текст описания: навыки и компетенции")
def extract(user: CurrentEmployer, text: str = Query(max_length=10000), specialization: Specialization = "backend",
            level: Level = "middle"):
    """Помогает заполнить стек: показывает, какие навыки и компетенции система увидит в описании."""
    return build_need_profile(specialization, level, [], text, None)


# ------------------------------------------------------------------ учётная запись


@router.delete("/account", status_code=204, responses=errors(403), summary="Удалить учётную запись работодателя")
def delete_account(user: CurrentEmployer, db: DB):
    """
    Право на удаление персональных данных (152-ФЗ) есть и у представителя
    работодателя:

    * действующие приглашения отзываются, вакансии закрываются, регулярные
      задания отключаются, подписки ATS удаляются;
    * контакты и реквизиты компании стираются, в истории кандидатов она
      остаётся как «Компания удалила учётную запись»;
    * сообщения представителя и копии писем на его адреса удаляются;
    * сессии завершаются, учётная запись отключается.

    Демо-учётную запись удалить нельзя (`demo_account`).
    """
    from app.services import interactions

    if user.is_demo:
        raise Forbidden("Демо-учётную запись удалить нельзя: ею пользуются все посетители стенда", code="demo_account")
    company = db.scalar(select(Company).where(Company.owner_user_id == user.id))
    forget_recipient(db, user.email, company.contact_email if company else None)
    if company is not None:
        for inv in db.scalars(select(Invitation).where(Invitation.company_id == company.id,
                                                       Invitation.status.in_(interactions.ACTIVE_INVITATION))):
            inv.status = "withdrawn"
            interactions.add_event(db, "invitation", inv.id, "employer", "withdrawn", "Компания удалила учётную запись")
        db.execute(update(Need).where(Need.company_id == company.id).values(is_published=False, status="closed"))
        db.execute(update(EmployerTask).where(EmployerTask.company_id == company.id).values(active=False))
        for endpoint in db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.company_id == company.id)):
            db.delete(endpoint)
        company.name = "Компания удалила учётную запись"
        for field in ("inn", "description", "website", "city", "contact_email", "contact_phone", "verification_comment"):
            setattr(company, field, None)
        company.verified, company.verification_status = False, "none"
    db.query(Message).filter(Message.sender_user_id == user.id).delete()
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    user.email = "deleted-%s@deleted.local" % user.id.hex[:12]
    user.password_hash = None
    user.external_sub = None
    user.is_active = False
    audit(db, None, "account.deleted", "user", user.id, role="employer")
    db.commit()
    return Response(status_code=204)
