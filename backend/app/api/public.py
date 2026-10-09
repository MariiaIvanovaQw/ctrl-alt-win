"""Справочники, ролевые профили (как формируется тест) и публичный список вакансий."""

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import get_settings
from app.data.role_profiles import DEMO_VACANCIES, ROLE_PROFILES
from app.errors import NotFound, errors
from app.models import Company, Need
from app.models.interactions import DECLINE_REASONS
from app.reference import (
    COMPETENCY_TITLES,
    DIRECTIONS_PLANNED,
    FSP_DISCIPLINES,
    FSP_EVENT_LEVELS,
    FSP_RESULTS,
    FSP_SPORT_RANKS,
    INDUSTRIES,
    LEVEL_TITLES,
    SKILLS,
    SOFT_SKILLS,
    SPECIALIZATIONS,
    TEAM_ROLES,
    TRACKS,
    WORK_FORMATS,
)
from app.schemas import Level, Specialization, VacancyOut
from app.security.deps import DB
from app.services import fsp as fsp_service
from app.services import trust
from app.services.bank import bank
from app.services.needs import build_need_profile, test_coverage
from app.services.vacancies import vacancy_out

router = APIRouter(prefix="/api/v1", tags=["Справочники и вакансии"])


class HealthOut(BaseModel):
    status: str
    bank_version: str
    bank_items: int


class ReferenceOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    demo_mode: bool = Field(description="Демо-стенд: открыты экспресс-режим теста и сброс попыток для жюри")
    minors: dict
    specializations: list[dict]
    salary: dict
    directions: list[dict]
    tracks: dict[str, list[dict]]
    levels: list[dict]
    industries: list[dict]
    work_formats: list[dict]
    team_roles: list[dict]
    soft_skills: list[dict]
    skills: list[dict]
    competencies: dict[str, list[dict]]
    decline_reasons: list[dict]
    fsp: dict


class ProfilePreviewOut(BaseModel):
    category: dict
    role_profile: dict
    competency_profile: dict
    blueprint: list[dict]
    mandatory_competencies: list[str]
    rules: dict
    variants: list[dict]
    overlap_first_two: float
    coverage: dict


class VacancyListOut(BaseModel):
    total: int
    items: list[VacancyOut]


class VacancyDetailOut(VacancyOut):
    company_trust: dict = Field(description="Показатели компании: дней на платформе, приглашения, доля принятых, жалобы")
    salary_warnings: list[str]


@router.get("/health", response_model=HealthOut, summary="Проверка работоспособности")
def health(db: DB):
    db.execute(select(1))
    b = bank()
    return {"status": "ok", "bank_version": b.version, "bank_items": len(b.items)}


@router.get("/reference", response_model=ReferenceOut, summary="Все справочники")
def reference():
    return {
        # демо-стенд: открыты служебные методы для жюри (сброс и экспресс-режим теста)
        "demo_mode": get_settings().demo_mode,
        "minors": {
            "min_age": get_settings().min_candidate_age,
            "work_age": get_settings().min_work_age,
            "adult_age": 18,
            "note": "С 14 лет — тест и категория; с 15 лет профиль виден работодателям и отклики возможны после согласия "
                    "законного представителя; приглашения — только на предложения с лёгким трудом и сокращённым временем",
        },
        "specializations": [{"slug": k, "title": v} for k, v in SPECIALIZATIONS.items()],
        "salary": {"basis": "gross", "note": "Все суммы указаны в рублях в месяц до вычета НДФЛ"},
        # «Отрасль» в ТЗ — IT-направление: готовые (есть банк заданий) и запланированные
        "directions": [{"slug": k, "title": v, "available": True} for k, v in SPECIALIZATIONS.items()]
        + [{"slug": k, "title": v, "available": False} for k, v in DIRECTIONS_PLANNED.items()],
        "tracks": {spec: [{"slug": k, "title": v} for k, v in items.items()] for spec, items in TRACKS.items()},
        "levels": [{"slug": k, "title": v} for k, v in LEVEL_TITLES.items()],
        "industries": [{"slug": k, "title": v} for k, v in INDUSTRIES.items()],
        "work_formats": [{"slug": k, "title": v} for k, v in WORK_FORMATS.items()],
        "team_roles": [{"slug": k, "title": v} for k, v in TEAM_ROLES.items()],
        "soft_skills": [{"slug": k, "title": v[0]} for k, v in SOFT_SKILLS.items()],
        "skills": [
            {"slug": slug, "title": title, "specializations": sorted(mapping)}
            for slug, (title, _aliases, mapping) in SKILLS.items()
        ],
        "competencies": {
            spec: [{"slug": c, "title": COMPETENCY_TITLES.get(c, c)} for c in comps]
            for spec, comps in bank().competencies.items()
        },
        "decline_reasons": [{"slug": k, "title": v} for k, v in DECLINE_REASONS.items()],
        "fsp": {
            "disciplines": [{"slug": k, "title": v} for k, v in FSP_DISCIPLINES.items()],
            "event_levels": [{"slug": k, "title": v} for k, v in FSP_EVENT_LEVELS.items()],
            "results": [{"slug": k, "title": v, "weight": fsp_service.RESULT_WEIGHTS.get(k)} for k, v in FSP_RESULTS.items()],
            "ranks": [{"slug": k, "title": v} for k, v in FSP_SPORT_RANKS.items()],
            "scoring": "вес = итог × exp(−лет/3); соревнования и дисциплины равноценны, роль в команде не учитывается; "
                       "участия без результата суммарно не больше 0,3; итог = 1 − exp(−сумма/1,2)",
        },
    }


@router.get("/assessment/profiles", response_model=list[dict], summary="Ролевые профили категорий")
def profiles():
    """Эталонные описания вакансий для каждой категории (специализация × грейд)."""
    return [
        {"specialization": spec, "level": level, **data}
        for (spec, level), data in ROLE_PROFILES.items()
    ]


@router.get("/assessment/profiles/{specialization}/{level}", response_model=ProfilePreviewOut, summary="Как формируется тест категории")
def profile_preview(specialization: Specialization, level: Level, seeds: int = Query(2, ge=2, le=5)):
    """
    Демонстрация механики тестирования на эталонном описании вакансии:
    план сборки (тип × полоса сложности), обязательные компетенции, и
    несколько персональных вариантов теста по разным сидам — с их составом
    (без текстов заданий), суммой баллов и пересечением. Варианты разные,
    но сопоставимые: сумма баллов и состав по типам совпадают.
    """
    b = bank()
    data = ROLE_PROFILES[(specialization, level)]
    profile = build_need_profile(specialization, level, data["typical_stack"], data["summary"], " ".join(data["responsibilities"]))
    variants = []
    for seed in range(9001, 9001 + seeds):
        test = b.assemble(specialization, level, seed)
        variants.append(
            {
                "seed": seed,
                "test_label": test["test_id"],
                "points_total": sum(i["score"] for i in test["items"]),
                "by_type": {t: sum(1 for i in test["items"] if i["type"] == t) for t in ("theory", "situational", "practical")},
                "competencies": sorted({i["competency"] for i in test["items"]}),
                "items": [
                    {"position": i["position"], "item_id": i["item_id"], "variant_id": i["variant_id"], "type": i["type"],
                     "competency": i["competency"], "difficulty": i["difficulty"], "score": i["score"]}
                    for i in test["items"]
                ],
            }
        )
    ids = [{i["item_id"] for i in v["items"]} for v in variants]
    overlap = len(ids[0] & ids[1]) / len(ids[0])
    return {
        "category": {"specialization": specialization, "level": level},
        "role_profile": data,
        "competency_profile": profile,
        "blueprint": [
            {"type": t, "difficulty_from": dmin, "difficulty_to": dmax, "count": n}
            for t, dmin, dmax, n in b.blueprint.BLUEPRINT[level]
        ],
        "mandatory_competencies": b.roles[specialization]["mandatory"],
        "rules": {
            "test_size": b.blueprint.TEST_SIZE,
            "competency_cap": b.blueprint.COMPETENCY_CAP,
            "min_competencies": b.blueprint.MIN_COMPETENCIES,
            "grade_rules": b.blueprint.GRADE_RULES[level],
        },
        "variants": variants,
        "overlap_first_two": round(overlap, 3),
        "coverage": test_coverage(specialization, level, profile["competency_weights"], seeds=10),
    }


@router.get("/assessment/demo-vacancies", response_model=list[dict], summary="Демонстрационные описания вакансий и их разбор")
def demo_vacancies():
    """Шесть описаний вакансий и профили компетенций, которые система из них строит."""
    out = []
    for v in DEMO_VACANCIES:
        out.append({**v, "profile": build_need_profile(v["specialization"], v["level"], v["stack"], v["description"], v["team_description"])})
    return out


@router.get("/vacancies", response_model=VacancyListOut, summary="Опубликованные вакансии")
def vacancies(
    db: DB,
    specialization: Specialization | None = None,
    level: Level | None = None,
    work_format: str | None = None,
    salary_min: int | None = Query(None, description="Верхняя граница вилки не ниже, ₽"),
    text: str | None = Query(None, max_length=200),
    for_minors: bool = Query(False, description="Только подходящие для несовершеннолетних (15–17 лет)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = (
        select(Need, Company)
        .join(Company, Company.id == Need.company_id)
        .where(Need.is_published.is_(True), Need.status == "open", Company.review_status == "active")
    )
    if specialization:
        query = query.where(Need.specialization == specialization)
    if level:
        query = query.where(Need.level == level)
    if work_format:
        query = query.where(Need.work_format.in_((work_format, "any")))
    if salary_min:
        query = query.where(Need.salary_to >= salary_min)
    if for_minors:
        query = query.where(Need.suitable_for_minors.is_(True))
    rows = db.execute(query.order_by(Need.published_at.desc())).all()
    items = [vacancy_out(n, c) for n, c in rows]
    if text:
        t = text.lower()
        items = [i for i in items if t in i["title"].lower() or t in i["description"].lower()]
    return {"total": len(items), "items": items[offset : offset + limit]}


@router.get("/vacancies/{vacancy_id}", response_model=VacancyDetailOut, responses=errors(404), summary="Вакансия")
def vacancy(vacancy_id: uuid.UUID, db: DB):
    need = db.get(Need, vacancy_id)
    company = db.get(Company, need.company_id) if need else None
    if need is None or not need.is_published or company.review_status != "active":
        raise NotFound("Вакансия не найдена")
    out = vacancy_out(need, company)
    out["company_trust"] = trust.company_trust(db, company)
    out["salary_warnings"] = trust.salary_warnings(db, need.salary_from, need.salary_to, need.specialization, need.level)
    return out
