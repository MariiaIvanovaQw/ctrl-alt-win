"""
Поиск по банку кандидатов и подборки под потребность.

Фильтры применяются поверх рассчитанного рейтинга, а подборка сохраняется
вместе с параметрами и снимком результата: уточнение создаёт новую
подборку-потомка и не теряет предыдущую.

Снимок подборки — это порядок кандидатов и обоснование места, но не их
карточки: карточка собирается при каждом открытии по текущим правам. Если
кандидат закрыл компании доступ к контактам, скрыл поле или удалил
учётную запись, старая подборка этого не обойдёт.

Фильтры работают только по тому, что кандидат показывает: текстовый поиск
не ищет по скрытому разделу «о себе», скрытый город считается неизвестным,
скрытые достижения ФСП не находятся фильтром «есть достижения ФСП».
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.errors import NotFound
from app.models import Company, Need, Selection, User
from app.services import matching, minors
from app.services.cards import build_card, contacts_reasons
from app.services.needs import build_need_profile


class SearchFilters(BaseModel):
    """Фильтры поиска; пустое значение означает «не фильтровать»."""

    specialization: Literal["backend", "frontend", "qa"] | None = Field(None, description="backend | frontend | qa")
    levels: list[Literal["junior", "middle", "senior"]] | None = Field(None, description="Грейды: junior, middle, senior")
    stack_all: list[str] | None = Field(None, max_length=30, description="Навыки, которые должны быть у кандидата (slug)")
    has_fsp: bool | None = Field(None, description="Только с подтверждёнными достижениями ФСП")
    city: str | None = Field(None, max_length=100)
    work_format: Literal["office", "hybrid", "remote"] | None = Field(None, description="office | hybrid | remote")
    salary_max: int | None = Field(None, ge=0, description="Ожидания кандидата не выше, ₽")
    track: str | None = Field(None, max_length=30, description="Специализация внутри направления (reference.tracks)")
    confirmed_only: bool = Field(False, description="Только с грейдом, подтверждённым тестом")
    hide_minors: bool = Field(False, description="Скрыть кандидатов младше 18 лет")
    within_budget: bool = Field(False, description="Для подборки: только с ожиданиями в пределах вилки")
    min_score: float | None = Field(None, ge=0, le=100, description="Минимальный балл соответствия или силы профиля")
    text: str | None = Field(None, max_length=200, description="Поиск по разделу «о себе», стеку и городу (только видимым)")
    limit: int = Field(50, ge=1, le=200)

    @field_validator("stack_all")
    @classmethod
    def _stack(cls, v):
        from app.schemas import check_skills

        return check_skills(v)


def _passes(f: matching.Facts, flt: SearchFilters, need: Need | None) -> bool:
    p = f.profile
    if not p.open_to_offers:
        return False
    if flt.levels and f.grade.level not in flt.levels:
        return False
    if flt.stack_all and not set(flt.stack_all) <= set(p.stack or []):
        return False
    if flt.has_fsp is not None and bool(matching.visible_fsp_top(f)) != flt.has_fsp:
        return False
    city = p.city if matching.shows(p, "show_city") else None  # скрытый город — неизвестный
    if flt.city and (city or "").strip().lower() != flt.city.strip().lower() and not p.relocation:
        return False
    if flt.work_format and p.work_formats and flt.work_format not in p.work_formats:
        return False
    if flt.track and p.primary_track != flt.track:
        return False
    if flt.confirmed_only and not matching.is_confirmed(f.grade):
        return False
    if flt.hide_minors and minors.is_minor(p):
        return False
    if flt.salary_max is not None and p.salary_expectation and p.salary_expectation > flt.salary_max:
        return False
    if need is not None and flt.within_budget and p.salary_expectation and p.salary_expectation > need.salary_to:
        return False
    if flt.text:
        about = p.about if matching.shows(p, "show_about") else None
        haystack = " ".join([about or "", " ".join(p.stack or []), city or ""]).lower()
        if flt.text.lower() not in haystack:
            return False
    return True


def search_bank(db: Session, company: Company, flt: SearchFilters) -> dict:
    facts = matching.load_facts(db, specialization=flt.specialization)
    rows = []
    for f in facts:
        if not _passes(f, flt, None):
            continue
        match = matching.score_for_category(f)
        if flt.min_score is not None and match["score"] < flt.min_score:
            continue
        rows.append((f, match))
    # подтверждённые всегда выше заявленных, затем грейд и сила профиля
    rows.sort(key=lambda r: (not matching.is_confirmed(r[0].grade), -matching.level_order(r[0].grade.level), -r[1]["score"]))
    total = len(rows)
    shown = rows[: flt.limit]
    reasons = contacts_reasons(db, company.id, [f.user.id for f, _m in shown])
    items = [
        {"candidate": build_card(f, contacts_reason=reasons.get(f.user.id)), "ranking": match}
        for f, match in shown
    ]
    return {"total": total, "items": items}


def need_profile(need: Need) -> dict:
    if not need.profile:
        need.profile = build_need_profile(
            need.specialization, need.level, need.stack or [], need.description, need.team_description
        )
    return need.profile


def rank_for_need(db: Session, need: Need, flt: SearchFilters) -> list[tuple[matching.Facts, dict]]:
    """Кандидаты подходящих категорий в порядке выдачи подборки."""
    profile = need_profile(need)
    targets = matching.target_levels(need.level)
    allowed_levels = flt.levels or [lvl for lvl, _ in targets]
    facts = matching.load_facts(db, specialization=need.specialization, levels=allowed_levels)
    target_titles = dict(targets)
    rows = []
    for f in facts:
        if not _passes(f, flt, need):
            continue
        match = matching.score_for_need(f, need, profile)
        if flt.min_score is not None and match["score"] < flt.min_score:
            continue
        match["category_role"] = target_titles.get(f.grade.level, "по фильтру")
        rows.append((f, match))
    # подтверждённые раньше заявленных; основная категория первой, внутри — по баллу
    rows.sort(key=lambda r: (not matching.is_confirmed(r[0].grade), 0 if r[0].grade.level == need.level else 1, -r[1]["score"]))
    return rows


def run_selection(
    db: Session, company: Company, need: Need, flt: SearchFilters, parent: Selection | None = None
) -> Selection:
    profile = need_profile(need)
    targets = matching.target_levels(need.level)
    rows = rank_for_need(db, need, flt)
    # в снимке — только место и обоснование; карточки собираются при открытии (selection_rows)
    results = [
        {"rank": rank, "candidate_id": f.user.public_id, "specialization": f.grade.specialization, "match": match}
        for rank, (f, match) in enumerate(rows[: flt.limit], start=1)
    ]
    by_level = {}
    for f, _m in rows:
        by_level[f.grade.level] = by_level.get(f.grade.level, 0) + 1
    selection = Selection(
        company_id=company.id,
        need_id=need.id,
        parent_id=parent.id if parent else None,
        params=flt.model_dump(exclude_none=True),
        results=results,
        summary={
            "total_matched": len(rows),
            "shown": len(results),
            "by_level": by_level,
            "recommended_categories": [
                {"level": lvl, "role": role, "candidates": by_level.get(lvl, 0)} for lvl, role in targets
            ],
            "need_profile": {"top_competencies": profile["top_competencies"], "skills": profile["skills"]},
            "created_at": utcnow().isoformat(),
        },
    )
    db.add(selection)
    db.commit()
    # данные кандидатов этого же запроса: selection_rows не читает их второй раз
    selection.fresh_facts = [f for f, _m in rows[: flt.limit]]
    return selection


def selection_rows(db: Session, company: Company, selection: Selection) -> tuple[list[dict], int]:
    """
    Строки подборки с карточками по текущим правам: контакты — только при
    действующем доступе, скрытые поля и достижения ФСП — скрыты. Кандидаты,
    закрывшие профиль или удалившие учётную запись, в подборку не попадают;
    возвращается и их число.
    """
    stored = selection.results or []
    facts = getattr(selection, "fresh_facts", None)  # подборка только что посчитана — данные актуальны
    if facts is None:
        ids = [row["candidate_id"] for row in stored]
        users = {u.public_id: u for u in db.scalars(select(User).where(User.public_id.in_(ids)))} if ids else {}
        facts = matching.load_facts(db, user_ids=[u.id for u in users.values()]) if users else []
    by_key = {(f.user.public_id, f.grade.specialization): f for f in facts}
    by_id: dict = {}
    for f in facts:
        by_id.setdefault(f.user.public_id, f)
    reasons = contacts_reasons(db, company.id, [f.user.id for f in facts])
    rows, unavailable = [], 0
    for row in stored:
        f = by_key.get((row["candidate_id"], row.get("specialization"))) or by_id.get(row["candidate_id"])
        if f is None:
            unavailable += 1
            continue
        rows.append({
            "rank": row["rank"],
            "candidate_id": row["candidate_id"],
            "candidate": build_card(f, contacts_reason=reasons.get(f.user.id)),
            "match": matching.sanitize_match(row["match"], f.profile),
        })
    return rows, unavailable


def get_selection(db: Session, company: Company, selection_id: uuid.UUID) -> Selection:
    selection = db.get(Selection, selection_id)
    if selection is None or selection.company_id != company.id:
        raise NotFound("Подборка не найдена")
    return selection


def selection_chain(db: Session, selection: Selection) -> list[dict]:
    chain = []
    current = selection
    while current is not None:
        chain.append({"id": str(current.id), "params": current.params, "total": current.summary.get("total_matched"),
                      "created_at": current.created_at.isoformat()})
        current = db.get(Selection, current.parent_id) if current.parent_id else None
    return list(reversed(chain))
