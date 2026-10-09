"""Сглаживание компетенций, профиль потребности и факторы ранжирования."""

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models import User
from app.services import matching
from app.services.competencies import smooth
from app.services.needs import build_need_profile
from app.services.needs import test_coverage as coverage_of
from tests.conftest import employer_with_company, graded_candidate, register, survey


def test_smoothing_shrinks_small_samples():
    # одно задание весом 2, решённое верно, при общем уровне кандидата 50 %
    one, conf_one = smooth(2, 2, 0.5)
    many, conf_many = smooth(20, 20, 0.5)
    assert 0.5 < one < many <= 1.0
    assert conf_one < conf_many < 1.0
    # без данных оценка равна общему уровню, достоверность нулевая
    assert smooth(0, 0, 0.62) == (0.62, 0.0)


def test_need_profile_from_text():
    profile = build_need_profile(
        "backend", "middle", ["python", "postgresql", "kafka"],
        "Проектируем REST API, ищем медленные запросы, индексы и N+1, работаем с очередями Kafka",
        "Код-ревью и CI/CD",
    )
    weights = profile["competency_weights"]
    assert weights, "профиль компетенций не пуст"
    assert "databases" in weights or "sql" in weights
    assert {"python", "postgresql", "kafka"} <= set(profile["skills"])
    coverage = coverage_of("backend", "middle", weights, seeds=3)
    assert coverage["competencies"]


def _facts(expectation=None, formats=None, city="Москва", relocation=False):
    profile = SimpleNamespace(salary_expectation=expectation, work_formats=formats or [], city=city, relocation=relocation)
    return SimpleNamespace(profile=profile)


def test_conditions_penalties():
    need = SimpleNamespace(salary_to=300000, work_format="office", city="Казань")
    penalty, notes, warnings, reasons = matching.conditions(_facts(250000, ["office"], "Казань"), need)
    assert penalty == 0 and notes and not warnings and not reasons
    penalty, _n, warnings, reasons = matching.conditions(_facts(350000, ["remote"], "Москва"), need)
    assert penalty == matching.PENALTY_SALARY + matching.PENALTY_FORMAT + matching.PENALTY_CITY
    assert len(warnings) == 3
    # разбор покрывает снижение целиком: доли причин дают сам коэффициент
    assert [r["title"] for r in reasons] == warnings
    assert sum(r["share"] for r in reasons) == penalty
    penalty, _n, _w, reasons = matching.conditions(_facts(250000, ["office"], "Москва", relocation=True), need)
    assert penalty == 0 and not reasons


def _attempt(**bands):
    buckets = {b: {"points_earned": e, "points_possible": p} for b, (e, p) in bands.items()}
    return SimpleNamespace(summary={"difficulty_buckets": buckets})


def test_band_rate_does_not_reward_missing_evidence():
    priors = {"easy": 0.8, "mid": 0.6, "hard": 0.4, "top": 0.3}
    # middle по тесту junior: несколько лёгких заданий d4–6 решены, d7–8 не было
    via_junior, detail = matching.band_rate(_attempt(easy=(10, 10), mid=(8, 8)), "middle", priors)
    # middle по тесту middle: много заданий обеих полос
    via_middle, _ = matching.band_rate(_attempt(mid=(28, 32), hard=(12, 18)), "middle", priors)
    assert via_junior < 0.8, "отсутствующая полоса не превращается в 100 %"
    assert via_junior < via_middle
    assert detail[1]["rate"] is None and detail[1]["smoothed"] == priors["hard"]
    # без данных — среднее категории
    empty, _ = matching.band_rate(_attempt(), "senior", priors)
    assert abs(empty - (0.6 * 0.4 + 0.4 * 0.3)) < 1e-9


def test_band_priors_need_enough_candidates():
    few = [_attempt(hard=(1, 10))] * (matching.BAND_PRIOR_MIN_CANDIDATES - 1)
    assert matching.band_priors(few)["hard"] == matching.DEFAULT_BAND_PRIOR["hard"]
    enough = [_attempt(hard=(1, 10))] * matching.BAND_PRIOR_MIN_CANDIDATES
    assert matching.band_priors(enough)["hard"] == 0.1


def test_target_levels():
    assert [lvl for lvl, _ in matching.target_levels("junior")] == ["junior", "middle"]
    assert [lvl for lvl, _ in matching.target_levels("middle")] == ["middle", "senior", "junior"]
    assert [lvl for lvl, _ in matching.target_levels("senior")] == ["senior", "middle"]


def test_weights_sum_to_one():
    assert abs(sum(matching.NEED_WEIGHTS.values()) - 1) < 1e-9
    assert abs(sum(matching.CATEGORY_WEIGHTS.values()) - 1) < 1e-9


def test_unconfirmed_candidates_are_shown_below_confirmed(client):
    from tests.conftest import publish_candidate, register

    graded_candidate(client, "frontend", "middle", stack=["react"])
    claimed = register(client)
    publish_candidate(client, claimed, stack=["react", "typescript"])
    survey(client, claimed, "frontend", "middle")  # опрос пройден, теста нет
    claimed_id = client.get("/api/v1/auth/me", headers=claimed.headers).json()["public_id"]
    emp = employer_with_company(client)

    found = client.post("/api/v1/employer/candidates/search", headers=emp.headers,
                        json={"specialization": "frontend", "limit": 200}).json()["items"]
    flags = [x["candidate"]["category"]["confirmed"] for x in found]
    assert False in flags and flags == sorted(flags, reverse=True), "подтверждённые всегда выше заявленных"
    row = next(x for x in found if x["candidate"]["candidate_id"] == claimed_id)
    assert row["candidate"]["category"]["status"] == "not_tested"
    assert "не подтверждён" in row["candidate"]["category"]["status_title"]

    only = client.post("/api/v1/employer/candidates/search", headers=emp.headers,
                       json={"specialization": "frontend", "confirmed_only": True, "limit": 200}).json()["items"]
    assert claimed_id not in {x["candidate"]["candidate_id"] for x in only}
    card = client.get("/api/v1/employer/candidates/%s" % claimed_id, headers=emp.headers)
    assert card.status_code == 200 and card.json()["category"]["confirmed"] is False
    cats = {(c["specialization"], c["level"]): c for c in client.get("/api/v1/employer/categories", headers=emp.headers).json()}
    assert cats[("frontend", "middle")]["unconfirmed"] >= 1


def _stack_facts(stack, estimates, spec="backend"):
    profile = SimpleNamespace(stack=stack, privacy={}, salary_expectation=None, work_formats=[], city=None, relocation=False)
    grade = SimpleNamespace(specialization=spec)
    est = {c: SimpleNamespace(estimate=v) for c, v in estimates.items()}
    return SimpleNamespace(profile=profile, grade=grade, estimates=est)


def test_declared_skills_count_half_without_test_confirmation():
    from app.services.textskills import skill_competencies

    comp = skill_competencies("python", "backend")[0]
    confirmed = matching.stack_fit(_stack_facts(["python"], {comp: 0.8}), ["python", "postgresql"])
    declared = matching.stack_fit(_stack_facts(["python"], {comp: 0.2}), ["python", "postgresql"])
    assert confirmed[0] == 0.5 and confirmed[3] == ["python"]
    assert declared[0] == 0.25 and declared[3] == []


def test_missing_salary_expectation_is_a_warning_not_a_penalty():
    need = SimpleNamespace(salary_to=300000, work_format="remote", city=None)
    penalty, _notes, warnings, _reasons = matching.conditions(_stack_facts([], {}), need)
    assert penalty == 0 and any("не указаны" in w for w in warnings)


def test_profile_edit_does_not_refresh_activity(client, db):
    from app.models import CandidateProfile

    acc = register(client)
    user = db.scalar(select(User).where(User.email == acc.email))
    profile = db.get(CandidateProfile, user.id)
    old = profile.last_active_at = profile.last_active_at - timedelta(days=100)
    db.commit()
    client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"city": "Томск"})
    db.expire_all()
    assert db.get(CandidateProfile, user.id).last_active_at == old
