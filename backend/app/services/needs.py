"""
Профиль потребности работодателя.

Из специализации, уровня, стека и текста описания строятся веса
компетенций банка. Основа — роли компетенций банка (обязательные,
ключевые, критические для senior), сверху — компетенции, на которые
указывают навыки стека и слова в описании. Именно эти веса сравниваются
с подтверждёнными тестом оценками кандидатов при подборе.
"""

from app.data.role_profiles import ROLE_PROFILES
from app.reference import COMPETENCY_TITLES, SKILLS
from app.services.bank import bank
from app.services.textskills import competency_mentions, extract_skills, skill_competencies

BASE_WEIGHT = 0.3
KEY_WEIGHT = 1.0
CRITICAL_WEIGHT = {"junior": 0.4, "middle": 0.6, "senior": 0.9}
SKILL_BOOST = 0.6
MENTION_BOOST = 0.25


def build_need_profile(specialization: str, level: str, stack: list[str], description: str, team: str | None) -> dict:
    b = bank()
    roles = b.roles[specialization]
    weights = dict.fromkeys(b.competencies[specialization], BASE_WEIGHT)
    sources: dict[str, list[str]] = {c: [] for c in weights}
    for c in set(roles["mandatory"]) | set(roles["key"]):
        weights[c] = KEY_WEIGHT
        sources[c].append("ключевая для специализации")
    for c in roles["critical"]:
        if CRITICAL_WEIGHT[level] > weights[c]:
            weights[c] = CRITICAL_WEIGHT[level]
        sources[c].append("критическая для уровня %s" % level.capitalize())

    text = "%s\n%s" % (description or "", team or "")
    from_text = [s["slug"] for s in extract_skills(text)]
    skills = list(dict.fromkeys([s for s in stack if s in SKILLS] + from_text))
    for slug in skills:
        for c in skill_competencies(slug, specialization):
            weights[c] += SKILL_BOOST
            sources[c].append("навык %s" % SKILLS[slug][0])
    for c, n in competency_mentions(text, specialization).items():
        weights[c] += MENTION_BOOST * min(n, 2)
        sources[c].append("упоминается в описании")

    top = max(weights.values())
    normalized = {c: round(w / top, 3) for c, w in weights.items()}
    ranked = sorted(normalized.items(), key=lambda kv: -kv[1])
    return {
        "competency_weights": normalized,
        "top_competencies": [
            {"competency": c, "title": COMPETENCY_TITLES.get(c, c), "weight": w, "sources": sorted(set(sources[c]))}
            for c, w in ranked[:8]
        ],
        "skills": skills,
        "skills_from_text": [s for s in from_text if s not in stack],
        "role_profile": ROLE_PROFILES[(specialization, level)]["title"],
    }


def test_coverage(specialization: str, level: str, weights: dict[str, float], seeds: int = 20) -> dict:
    """
    Как стандартный тест категории покрывает компетенции потребности.

    Тест один для всей категории (иначе результаты кандидатов несопоставимы),
    поэтому здесь показывается, какие компетенции потребности измеряются
    в каждой попытке, а какие — в части попыток и с какой частотой.
    """
    b = bank()
    mandatory = set(b.roles[specialization]["mandatory"])
    counts = dict.fromkeys(weights, 0)
    present = dict.fromkeys(weights, 0)
    for seed in range(7001, 7001 + seeds):
        test = b.assemble(specialization, level, seed)
        seen = set()
        for item in test["items"]:
            counts[item["competency"]] = counts.get(item["competency"], 0) + 1
            seen.add(item["competency"])
        for c in seen:
            present[c] = present.get(c, 0) + 1
    rows = []
    for c, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        rows.append(
            {
                "competency": c,
                "title": COMPETENCY_TITLES.get(c, c),
                "weight": w,
                "mandatory_in_test": c in mandatory,
                "share_of_attempts": round(present.get(c, 0) / seeds, 2),
                "items_per_attempt": round(counts.get(c, 0) / seeds, 2),
            }
        )
    return {"seeds_simulated": seeds, "competencies": rows}
