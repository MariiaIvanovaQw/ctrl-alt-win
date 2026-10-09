"""
Карточка кандидата для работодателя и правила раскрытия контактов.

Работодатель видит обезличенную карточку: псевдоним кандидата, категорию,
подтверждённые тестом результаты, заявленный стек, ожидания и достижения
ФСП (если кандидат их не скрыл). Контакты раскрываются только после того,
как кандидат принял приглашение этой компании или сам откликнулся на её
вакансию; каждое раскрытие пишется в журнал аудита.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Invitation
from app.reference import COMPETENCY_TITLES, SKILLS, SPECIALIZATIONS, TEAM_ROLES, WORK_FORMATS, track_title
from app.services import fsp as fsp_service
from app.services import minors
from app.services.competencies import confidence_label
from app.services.consents import audit
from app.services.matching import CLAIM_STATUS_TITLES
from app.services.matching import is_confirmed as matching_confirmed


def contacts_reasons(db: Session, company_id: uuid.UUID, candidate_user_ids: list) -> dict:
    """Основания раскрытия контактов сразу для списка кандидатов (два запроса вместо двух на кандидата)."""
    if not candidate_user_ids:
        return {}
    reasons = dict.fromkeys(db.scalars(select(Application.candidate_user_id).where(Application.company_id == company_id, Application.candidate_user_id.in_(candidate_user_ids), Application.status != "withdrawn", Application.contacts_revoked_at.is_(None))), "candidate_applied")
    for uid in db.scalars(select(Invitation.candidate_user_id).where(
        Invitation.company_id == company_id,
        Invitation.candidate_user_id.in_(candidate_user_ids),
        Invitation.status == "accepted",
        Invitation.contacts_revoked_at.is_(None),
    )):
        reasons[uid] = "invitation_accepted"  # принятое приглашение важнее отклика, как в contacts_access
    return reasons


def contacts_access(db: Session, company_id: uuid.UUID, candidate_user_id: uuid.UUID) -> str | None:
    """Основание раскрытия контактов или None."""
    accepted = db.scalar(
        select(Invitation.id).where(
            Invitation.company_id == company_id,
            Invitation.candidate_user_id == candidate_user_id,
            Invitation.status == "accepted",
            Invitation.contacts_revoked_at.is_(None),
        )
    )
    if accepted:
        return "invitation_accepted"
    applied = db.scalar(
        select(Application.id).where(
            Application.company_id == company_id,
            Application.candidate_user_id == candidate_user_id,
            Application.status != "withdrawn",
            Application.contacts_revoked_at.is_(None),
        )
    )
    if applied:
        return "candidate_applied"
    return None


def initials(full_name: str | None) -> str | None:
    if not full_name:
        return None
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0]
    # «Фамилия Имя Отчество» и «Имя Фамилия» — показываем имя и инициал
    first, last = (parts[1], parts[0]) if len(parts) >= 3 else (parts[0], parts[1])
    return "%s %s." % (first, last[0])


def display_name(user, profile) -> str:
    privacy = profile.privacy or {}
    if privacy.get("show_full_name") and profile.full_name:
        return profile.full_name
    return initials(profile.full_name) or "Кандидат %s" % user.public_id


def competency_rows(estimates: dict, limit: int | None = None) -> list[dict]:
    rows = sorted(estimates.values(), key=lambda e: -e.estimate)
    if limit:
        rows = rows[:limit]
    return [
        {
            "competency": e.competency,
            "title": COMPETENCY_TITLES.get(e.competency, e.competency),
            "estimate": round(e.estimate, 3),
            "raw_rate": e.raw_rate,
            "items": e.items,
            "confidence": round(e.confidence, 3),
            "confidence_label": confidence_label(e.confidence),
        }
        for e in rows
    ]


def build_card(facts, *, contacts_reason: str | None = None, full: bool = False, respect_privacy: bool = True) -> dict:
    """
    Карточка для работодателя. respect_privacy=False — личная копия самого
    кандидата (его PDF-профиль): скрытые от работодателей поля в ней видны.
    """
    user, profile, grade = facts.user, facts.profile, facts.grade
    privacy = (profile.privacy or {}) if respect_privacy else {}
    attempt = facts.attempt
    card = {
        "candidate_id": user.public_id,
        "display_name": display_name(user, profile),
        "city": profile.city if privacy.get("show_city", True) else None,
        "relocation": profile.relocation,
        "category": {
            "specialization": grade.specialization,
            "specialization_title": SPECIALIZATIONS.get(grade.specialization, grade.specialization),
            "track": profile.primary_track if profile.primary_specialization == grade.specialization else None,
            "track_title": track_title(grade.specialization, profile.primary_track)
            if profile.primary_specialization == grade.specialization
            else None,
            "level": grade.level,
            "confirmed": matching_confirmed(grade),
            "status": getattr(grade, "status", "confirmed"),
            "status_title": "подтверждён тестом"
            if matching_confirmed(grade)
            else "не подтверждён: " + CLAIM_STATUS_TITLES.get(getattr(grade, "status", ""), ""),
            "confirmed_at": grade.assigned_at.isoformat() if grade.assigned_at else None,
        },
        "test": {
            "score": attempt.score if attempt else None,
            "declared_level": attempt.declared_level if attempt else None,
            "finished_at": attempt.finished_at.isoformat() if attempt and attempt.finished_at else None,
            "level_band_rate": round(facts.band_rate, 3),
            "level_band_detail": facts.band_detail,
            "percentile_in_category": round(facts.percentile, 3),
            "attempts_total": facts.attempts_count,
        },
        "competencies": competency_rows(facts.estimates, None if full else 5),
        "stack": [{"slug": s, "title": SKILLS[s][0]} for s in (profile.stack or []) if s in SKILLS],
        "experience_years": profile.experience_years if privacy.get("show_experience", True) else None,
        "roles": [{"slug": r, "title": TEAM_ROLES.get(r, r)} for r in (profile.roles or [])],
        "work_formats": [{"slug": w, "title": WORK_FORMATS.get(w, w)} for w in (profile.work_formats or [])],
        "salary_expectation": profile.salary_expectation,
        "open_to_offers": profile.open_to_offers,
        # возрастная группа без даты рождения: работодателю нужно знать только ограничения
        "minor": minors.is_minor(profile),
        "minor_note": minors.MINOR_NOTE if minors.is_minor(profile) else None,
        "last_active_at": profile.last_active_at.isoformat() if profile.last_active_at else None,
        "fsp": _fsp_block(facts, privacy),
        "regular_tasks": {"solved": facts.tasks_solved, "avg_quality": round(facts.tasks_quality, 2)},
        "contacts": None,
        "contacts_visible": False,
        "contacts_note": "Контакты откроются, когда кандидат примет приглашение или сам откликнется на вакансию",
    }
    if full:
        card["about"] = profile.about if privacy.get("show_about", True) else None
        card["soft_skills"] = profile.soft_skills or []
        card["test"]["grade_decision"] = _decision_summary(attempt)
        # признаки для разбора по определяющей попытке; на грейд не влияют
        card["test"]["flags"] = [
            {"code": f.get("code"), "message": f.get("message")}
            for f in ((getattr(attempt, "flags", None) or []) if attempt is not None else [])
        ]
    if contacts_reason:
        card["contacts"] = {
            "full_name": profile.full_name,
            "email": profile.contact_email or user.email,
            "phone": profile.phone,
            "telegram": profile.telegram,
        }
        card["contacts_visible"] = True
        card["contacts_note"] = CONTACT_NOTES[contacts_reason]
    return card


CONTACT_NOTES = {
    "invitation_accepted": "Кандидат принял ваше приглашение",
    "candidate_applied": "Кандидат откликнулся на вашу вакансию",
    "own_copy": "Личная копия кандидата",
}


def placeholder_facts(db: Session, user, profile):
    """
    Сведения для PDF-профиля кандидата, у которого ещё нет ни опроса, ни
    категории: категория «не присвоена», остальное — из профиля и ФСП.
    """
    from app.models import FspLink
    from app.services.matching import ClaimedGrade, Facts

    achievements = fsp_service.achievements_of(db, user.id)
    link = db.get(FspLink, user.id)
    grade = ClaimedGrade(user.id, profile.primary_specialization or "направление не выбрано", "не присвоен", "not_tested")
    facts = Facts(user=user, profile=profile, grade=grade, attempt=None, achievements=achievements,
                  fsp_linked=link is not None, fsp_rank=link.sport_rank if link else None)
    facts.fsp = fsp_service.fsp_score(achievements)
    return facts


def _fsp_block(facts, privacy: dict) -> dict:
    if not privacy.get("show_fsp", True):
        return {"linked": None, "hidden_by_candidate": True, "score": None, "headline": None, "achievements": [],
                "note": "Кандидат скрыл достижения ФСП: они не показываются и не учитываются в ранжировании"}
    if not facts.fsp_linked:
        return {
            "linked": False,
            "hidden_by_candidate": False,
            "score": 0.0,
            "headline": None,
            "achievements": [],
            "note": "Кандидат не привязал ФСП ID — это не влияет на остальные показатели",
        }
    return {
        "linked": True,
        "hidden_by_candidate": False,
        "score": facts.fsp.get("score", 0.0),
        "headline": fsp_service.headline(facts.achievements, facts.grade.specialization),
        "sport_rank": facts.fsp_rank,
        "sport_rank_title": fsp_service.rank_title(facts.fsp_rank),
        "stats": facts.fsp.get("stats") or fsp_service.fsp_stats(facts.achievements),
        "achievements": [fsp_service.describe(a) for a in facts.achievements],
    }


def _decision_summary(attempt) -> dict | None:
    summary = getattr(attempt, "summary", None) if attempt is not None else None
    if not summary:
        return None
    decision = summary.get("grade_decision") or {}
    return {
        "outcome": decision.get("outcome"),
        "confirmed_level": decision.get("confirmed_level"),
        "metrics": decision.get("metrics"),
    }


def log_contact_view(db: Session, employer_user_id, candidate_user_id, reason: str) -> None:
    audit(db, employer_user_id, "contacts.viewed", "candidate", candidate_user_id, reason=reason)
