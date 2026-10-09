"""
Выгрузка кандидата для ATS работодателя в формате JSON Resume
(https://jsonresume.org/schema). Его понимают многие ATS и конвертеры.
Подтверждённые платформой сведения (категория, тест, компетенции, ФСП)
лежат в расширении `x-talent`.

Выгрузка подчиняется тем же правилам видимости, что и карточка:
контакты и полное имя — только если кандидат принял приглашение компании
или откликнулся на её вакансию; поля, скрытые настройками приватности,
не выгружаются.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFound
from app.models import CandidateProfile, User
from app.reference import LEVEL_TITLES, SKILLS, SPECIALIZATIONS
from app.services import matching
from app.services.cards import build_card, contacts_access, display_name
from app.services.consents import has_consent


def candidate_json_resume(db: Session, company_id, candidate: User) -> dict:
    reason = contacts_access(db, company_id, candidate.id)
    if reason is None and not has_consent(db, candidate.id, "profile_publication"):
        raise NotFound("Кандидат не найден")
    profile = db.get(CandidateProfile, candidate.id)
    facts = matching.load_facts(db, user_ids=[candidate.id], only_published=reason is None)
    if facts:
        chosen = next((f for f in facts if f.grade.specialization == profile.primary_specialization), facts[0])
        card = build_card(chosen, contacts_reason=reason, full=True)
    else:
        card = None
    return _render(candidate, profile, card, reason)


def _render(candidate: User, profile: CandidateProfile, card: dict | None, reason: str | None) -> dict:
    privacy = profile.privacy or {}
    contacts = card["contacts"] if card else None
    if card is None and reason:
        contacts = {"full_name": profile.full_name, "email": profile.contact_email or candidate.email,
                    "phone": profile.phone, "telegram": profile.telegram}
    category = card["category"] if card else None
    label = None
    if category:
        label = "%s · %s" % (category["specialization_title"], LEVEL_TITLES.get(category["level"], category["level"]))
    basics = {
        "name": (contacts or {}).get("full_name") or display_name(candidate, profile),
        "label": label,
        "summary": profile.about if privacy.get("show_about", True) else None,
        "location": {"city": profile.city, "countryCode": "RU"} if profile.city and privacy.get("show_city", True) else None,
        "url": get_settings().frontend_url.rstrip("/") + "/employer/candidates/" + candidate.public_id,
    }
    if contacts:
        basics["email"] = contacts.get("email")
        basics["phone"] = contacts.get("phone")
        if contacts.get("telegram"):
            basics["profiles"] = [{"network": "Telegram", "username": contacts["telegram"].lstrip("@"),
                                   "url": "https://t.me/" + contacts["telegram"].lstrip("@")}]
    skills = []
    if card:
        for comp in card["competencies"]:
            skills.append({"name": comp["title"], "level": "%d%%" % round(comp["estimate"] * 100),
                           "keywords": ["подтверждено тестом", "достоверность: " + comp["confidence_label"]]})
    declared = [SKILLS[s][0] for s in (profile.stack or []) if s in SKILLS]
    if declared:
        skills.append({"name": "Стек (заявлено кандидатом)", "keywords": declared})
    talent = {
        "candidate_id": candidate.public_id,
        "contacts_visible": bool(contacts),
        "contacts_reason": reason,
        "category": category,
        "specialization_title": SPECIALIZATIONS.get(profile.primary_specialization or "", None),
        "experience_years": profile.experience_years if privacy.get("show_experience", True) else None,
        "salary_expectation_rub": profile.salary_expectation,
        "work_formats": profile.work_formats or [],
        "relocation": profile.relocation,
        "test": None if card is None else {k: card["test"].get(k) for k in (
            "score", "declared_level", "finished_at", "level_band_rate", "percentile_in_category", "attempts_total")},
        "fsp": None if card is None else card["fsp"],
        "regular_tasks": None if card is None else card["regular_tasks"],
    }
    return {
        "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
        "basics": {k: v for k, v in basics.items() if v not in (None, [], "")},
        "skills": skills,
        "languages": [],
        "meta": {"version": "v1.0.0", "source": "Платформа подбора ИТ-специалистов ФСП"},
        "x-talent": talent,
    }
