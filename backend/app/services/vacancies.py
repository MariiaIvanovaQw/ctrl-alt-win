"""Представление вакансии для кандидатов и публичного списка."""

from app.models import Company, Need
from app.reference import SALARY_BASIS, SALARY_NOTE, SKILLS, SPECIALIZATIONS, WORK_FORMATS


def vacancy_out(need: Need, company: Company) -> dict:
    return {
        "id": str(need.id),
        "title": need.title,
        "company": {"id": str(company.id), "name": company.name, "industry": company.industry, "city": company.city},
        "specialization": need.specialization,
        "specialization_title": SPECIALIZATIONS.get(need.specialization, need.specialization),
        "level": need.level,
        "description": need.description,
        "team_description": need.team_description,
        "stack": [{"slug": s, "title": SKILLS[s][0]} for s in (need.stack or []) if s in SKILLS],
        "work_format": need.work_format,
        "work_format_title": WORK_FORMATS.get(need.work_format, "Любой"),
        "city": need.city,
        "salary_from": need.salary_from,
        "salary_to": need.salary_to,
        "salary_basis": SALARY_BASIS,
        "salary_note": SALARY_NOTE,
        "status": need.status,
        # подходит для несовершеннолетних (15–17 лет): лёгкий труд, сокращённое время, без вредных условий
        "suitable_for_minors": bool(need.suitable_for_minors),
        "published_at": need.published_at.isoformat() if need.published_at else None,
    }
