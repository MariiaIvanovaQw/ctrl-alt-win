"""
Тестирование: что уходит клиенту, жизненный цикл попытки и правила
платформы для грейда (без принудительного понижения, лимиты пересдач).
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, utcnow
from app.models import Attempt, CandidateGrade, GradeRecommendation, User
from app.services import assessment
from tests.conftest import (
    employer_with_company,
    graded_candidate,
    pass_test,
    public_id,
    publish_candidate,
    register,
    survey,
)

CLIENT_FIELDS = {"position", "type", "validation_type", "question", "language", "code", "options"}


def test_survey_is_required_before_test(client):
    acc = register(client)
    r = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": "backend", "level": "junior"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "survey_required"


def test_client_gets_no_answer_keys(client):
    acc = register(client)
    survey(client, acc, "qa", "junior")
    r = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": "qa", "level": "junior"})
    assert r.status_code == 201
    attempt = r.json()
    assert len(attempt["items"]) == 26
    for item in attempt["items"]:
        assert set(item) <= CLIENT_FIELDS, set(item) - CLIENT_FIELDS
        for option in item.get("options") or []:
            assert set(option) == {"id", "text"}
    assert attempt["test_label"].startswith("QA-J-") and len(attempt["test_label"]) == 21
    # метка не раскрывает сид: по сиду и открытому банку тест собирается вместе с ключами
    with SessionLocal() as s:
        seed = s.get(Attempt, uuid.UUID(attempt["id"])).seed
    assert ("%016X" % seed) not in attempt["test_label"] and ("%X" % seed) not in attempt["test_label"]
    assert str(seed) not in str(attempt)
    # вторая попытка, пока идёт первая, запрещена
    r = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": "qa", "level": "middle"})
    assert r.json()["error"]["code"] == "attempt_in_progress"


def test_invalid_answer_rejected(client):
    acc = register(client)
    survey(client, acc, "frontend", "junior")
    attempt = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                          json={"specialization": "frontend", "level": "junior"}).json()
    choice = next(i for i in attempt["items"] if i["validation_type"] == "single_choice")
    r = client.put("/api/v1/candidate/assessment/attempts/%s/answers/%d" % (attempt["id"], choice["position"]),
                   headers=acc.headers, json={"value": "Z"})
    assert r.json()["error"]["code"] == "invalid_answer"


def test_attempt_labels_and_seeds_are_unique(client, db):
    labels = set()
    for _ in range(3):
        acc = register(client)
        survey(client, acc, "backend", "junior")
        attempt = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                              json={"specialization": "backend", "level": "junior"}).json()
        labels.add(attempt["test_label"])
    assert len(labels) == 3


def test_full_flow_assigns_category_and_locks_retakes(client):
    acc = register(client)
    publish_candidate(client, acc)
    survey(client, acc, "backend", "middle")
    result = pass_test(client, acc, "backend", "middle")
    assert result["result"]["outcome"] == "confirmed"
    assert result["result"]["applied"]["action"] == "assigned"
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert status["grade"]["level"] == "middle"
    reasons = {a["level"]: a["reason"] for a in status["availability"]}
    assert reasons == {"junior": "grade_change_cooldown", "middle": "retry_cooldown", "senior": "grade_change_cooldown"}
    assert status["competencies"], "оценки компетенций рассчитаны"
    for row in status["competencies"]:
        assert 0 <= row["confidence"] < 1


def test_expired_attempt_is_finished_with_given_answers(client, db):
    acc = register(client)
    survey(client, acc, "qa", "junior")
    attempt = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                          json={"specialization": "qa", "level": "junior"}).json()
    row = db.get(Attempt, uuid.UUID(attempt["id"]))
    row.deadline_at = utcnow() - timedelta(minutes=1)
    db.commit()
    r = client.get("/api/v1/candidate/assessment/attempts/%s" % attempt["id"], headers=acc.headers)
    assert r.json()["status"] == "finished"
    r = client.put("/api/v1/candidate/assessment/attempts/%s/answers/0" % attempt["id"], headers=acc.headers, json={"value": "A"})
    assert r.json()["error"]["code"] == "attempt_expired"


# ---------------------------------------------------------------- правила грейда


def _finished(db, user: User, spec: str, declared: str, confirmed: str, days_ago: float = 0) -> Attempt:
    """Готовая попытка с заданным свидетельством уровня — для проверки правил платформы."""
    now = utcnow() - timedelta(days=days_ago)
    attempt = Attempt(
        user_id=user.id, specialization=spec, declared_level=declared, seed=uuid.uuid4().int >> 66,
        bank_version="test", test_label="TEST", status="finished", started_at=now - timedelta(minutes=30),
        deadline_at=now + timedelta(minutes=30), finished_at=now, confirmed_level=confirmed,
        outcome="confirmed" if confirmed == declared else "downgraded", score=50,
    )
    db.add(attempt)
    db.flush()
    return attempt


def _user(client, db) -> User:
    acc = register(client)
    return db.scalar(select(User).where(User.email == acc.email))


def test_lower_result_becomes_recommendation_not_downgrade(client, db):
    user = _user(client, db)
    applied = assessment.apply_result(db, _finished(db, user, "backend", "senior", "middle"))
    db.commit()
    assert applied["action"] == "recommendation"
    assert assessment.get_grade(db, user.id, "backend") is None
    rec = db.scalar(select(GradeRecommendation).where(GradeRecommendation.user_id == user.id))
    assert rec.recommended_level == "middle"
    assessment.accept_recommendation(db, user, "backend")
    assert assessment.get_grade(db, user.id, "backend").level == "middle"


def test_existing_grade_is_never_lowered_by_failed_attempt(client, db):
    user = _user(client, db)
    assessment.apply_result(db, _finished(db, user, "qa", "middle", "middle", days_ago=200))
    db.commit()
    applied = assessment.apply_result(db, _finished(db, user, "qa", "senior", "junior"))
    db.commit()
    assert applied["action"] == "kept"
    assert assessment.get_grade(db, user.id, "qa").level == "middle"


def test_candidate_may_lower_grade_by_choice(client, db):
    user = _user(client, db)
    assessment.apply_result(db, _finished(db, user, "frontend", "middle", "middle", days_ago=200))
    db.commit()
    applied = assessment.apply_result(db, _finished(db, user, "frontend", "junior", "junior"))
    db.commit()
    assert applied["action"] == "lowered_by_choice"
    assert assessment.get_grade(db, user.id, "frontend").level == "junior"


def test_no_recommendation_after_recent_failure(client, db):
    user = _user(client, db)
    assessment.apply_result(db, _finished(db, user, "backend", "senior", "below_junior", days_ago=40))
    db.commit()
    applied = assessment.apply_result(db, _finished(db, user, "backend", "senior", "middle"))
    db.commit()
    assert applied["action"] == "verify_required"
    assert assessment.open_recommendation(db, user.id, "backend") is None
    assert assessment.get_grade(db, user.id, "backend") is None


def test_recommendation_allowed_after_clean_period(client, db):
    user = _user(client, db)
    assessment.apply_result(db, _finished(db, user, "backend", "senior", "below_junior", days_ago=400))
    db.commit()
    applied = assessment.apply_result(db, _finished(db, user, "backend", "senior", "middle"))
    assert applied["action"] == "recommendation"


def test_grade_change_cooldown(client, db):
    acc = register(client)
    user = db.scalar(select(User).where(User.email == acc.email))
    survey(client, acc, "backend", "junior")
    assessment.apply_result(db, _finished(db, user, "backend", "junior", "junior", days_ago=10))
    db.commit()
    avail = {a.level: a for a in assessment.availability(db, user, "backend")}
    assert not avail["middle"].allowed and avail["middle"].reason == "grade_change_cooldown"
    grade = db.scalar(select(CandidateGrade).where(CandidateGrade.user_id == user.id))
    grade.last_change_at = utcnow() - timedelta(days=91)
    db.commit()
    avail = {a.level: a for a in assessment.availability(db, user, "backend")}
    assert avail["middle"].allowed


def test_promotion_requires_separate_test(client):
    """Сильный результат на тесте junior не даёт middle автоматически, а открывает тест middle без ожидания."""
    acc = register(client)
    survey(client, acc, "backend", "junior")
    result = pass_test(client, acc, "backend", "junior")
    applied = result["result"]["applied"]
    assert applied["action"] == "assigned" and applied["level"] == "junior"
    assert applied["promotion_offer"]["level"] == "middle"
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert status["grade"]["level"] == "junior" and status["grade"]["promotion_offer"]["level"] == "middle"
    avail = {a["level"]: a for a in status["availability"]}
    assert avail["middle"]["allowed"], "пропуск снимает ожидание смены грейда"
    assert not avail["senior"]["allowed"]
    result = pass_test(client, acc, "backend", "middle")
    assert result["result"]["applied"]["action"] == "promoted"
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert status["grade"]["level"] == "middle" and status["grade"]["promotion_offer"] is None


def test_demo_reset_allows_retaking(client):
    acc = register(client)
    survey(client, acc, "qa", "junior")
    pass_test(client, acc, "qa", "junior")
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert {a["level"]: a["allowed"] for a in status["availability"]}["junior"] is False
    assert client.post("/api/v1/dev/me/reset-assessment", headers=acc.headers).status_code == 200
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert status["grade"] is None and all(a["allowed"] for a in status["availability"])


def test_demo_autofill_keeps_given_answers_and_grades(client):
    acc = register(client)
    survey(client, acc, "backend", "middle")
    attempt = client.post(
        "/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": "backend", "level": "middle"}
    ).json()
    url = f"/api/v1/candidate/assessment/attempts/{attempt['id']}"
    first = attempt["items"][0]
    given = first["options"][0]["id"] if first.get("options") else "42"
    if first["validation_type"] == "multiple_choice":
        given = [given]
    client.put(f"{url}/answers/0", headers=acc.headers, json={"value": given})

    r = client.post(f"/api/v1/dev/me/attempts/{attempt['id']}/autofill", headers=acc.headers, json={"answer_as": "senior"})
    assert r.status_code == 200
    assert r.json()["filled"] == len(attempt["items"]) - 1
    done = client.get(url, headers=acc.headers).json()
    assert done["status"] == "finished" and done["result"]["finish_reason"] == "demo_autofill"
    assert done["answers"]["0"] == given, "свой ответ жюри не перезаписывается"
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers).json()
    assert status["grade"]["level"] == "middle", "сильные ответы подтверждают заявленный уровень"
    again = client.post(f"/api/v1/dev/me/attempts/{attempt['id']}/autofill", headers=acc.headers, json={"answer_as": "junior"})
    assert again.status_code == 409


def test_proctoring_signals_become_flags_not_grade(client):
    acc = register(client)
    survey(client, acc, "qa", "junior")
    attempt = client.post(
        "/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": "qa", "level": "junior"}
    ).json()
    url = f"/api/v1/candidate/assessment/attempts/{attempt['id']}"
    for kind in ("focus_lost", "focus_lost", "focus_lost", "copy"):
        assert client.post(f"{url}/signals", headers=acc.headers, json={"kind": kind}).status_code == 204
    assert client.post(f"{url}/signals", headers=acc.headers, json={"kind": "screenshot"}).status_code == 422
    result = client.post(f"{url}/finish", headers=acc.headers).json()["result"]
    codes = {f["code"] for f in result["flags"]}
    assert {"focus_lost", "copy_paste"} <= codes
    assert result["applied"]["action"] == "not_confirmed", "пустая попытка: грейд решают ответы, а не сигналы"
    assert client.post(f"{url}/signals", headers=acc.headers, json={"kind": "copy"}).status_code == 204


def test_only_one_active_attempt_in_database(client, db):
    acc = register(client)
    survey(client, acc, "qa", "junior")
    first = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                        json={"specialization": "qa", "level": "junior"}).json()
    row = db.get(Attempt, uuid.UUID(first["id"]))
    clone = Attempt(user_id=row.user_id, specialization="qa", declared_level="middle", seed=row.seed + 1,
                    bank_version=row.bank_version, test_label="x", deadline_at=row.deadline_at)
    db.add(clone)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def _availability(client, acc, spec):
    status = client.get("/api/v1/candidate/assessment/status", headers=acc.headers, params={"specialization": spec}).json()
    return {a["level"]: a for a in status["availability"]}


def test_after_failure_only_lower_levels_are_open(client):
    acc = register(client)
    survey(client, acc, "frontend", "middle")
    pass_test(client, acc, "frontend", "middle", correct=False)
    levels = _availability(client, acc, "frontend")
    assert levels["junior"]["allowed"] is True, "провал и уход ниже — без ожидания"
    assert levels["middle"]["reason"] == "retry_cooldown"
    assert levels["senior"]["allowed"] is False and levels["senior"]["reason"] == "failed_recently"


def test_failing_lower_test_keeps_grade_but_flags_card(client, db):
    from app.models import CandidateGrade

    cand = graded_candidate(client, "qa", "middle")
    user = db.scalar(select(User).where(User.email == cand.email))
    grade = db.scalar(select(CandidateGrade).where(CandidateGrade.user_id == user.id))
    grade.last_change_at = grade.last_change_at - timedelta(days=200)  # срок смены грейда прошёл
    db.commit()
    result = pass_test(client, cand, "qa", "junior", correct=False)
    assert result["result"]["applied"]["action"] == "kept"
    emp = employer_with_company(client)
    card = client.get("/api/v1/employer/candidates/%s" % public_id(client, cand), headers=emp.headers).json()
    assert card["category"]["level"] == "middle"
    assert any(f["code"] == "lower_test_failed" for f in card["test"]["flags"])


def test_item_exposure_counts_shown_items(client, db):
    from app.services.assessment import item_exposure

    before = item_exposure(db, "backend")
    acc = register(client)
    survey(client, acc, "backend", "junior")
    attempt = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                          json={"specialization": "backend", "level": "junior"}).json()
    after = item_exposure(db, "backend")
    assert sum(after.values()) - sum(before.values()) == len(attempt["items"])


def test_assessment_status_survives_connection_reuse_after_commit(client, monkeypatch):
    """Под нагрузкой соединение, вернувшееся в пул на commit, забирает другой запрос или пул его закрывает."""
    from sqlalchemy.orm import Session

    from app.db import engine

    cand = graded_candidate(client, "backend", "junior")
    real_commit = Session.commit

    def commit_and_drop_pool(self):
        real_commit(self)
        engine.dispose()  # закрыть соединения в пуле — как при нехватке соединений под нагрузкой

    monkeypatch.setattr(Session, "commit", commit_and_drop_pool)
    r = client.get("/api/v1/candidate/assessment/status", headers=cand.headers)
    assert r.status_code == 200
    assert r.json()["grade_history"]


def test_candidate_can_hold_categories_in_two_specializations(client):
    """Категории в нескольких направлениях: грейд хранится отдельно для каждой специализации."""
    cand = graded_candidate(client, "backend", "middle")
    survey(client, cand, "qa", "junior", birth_date=None)
    result = pass_test(client, cand, "qa", "junior")
    assert result["result"]["applied"]["action"] == "assigned"
    grades = {g["specialization"]: g["level"] for g in client.get("/api/v1/candidate/profile", headers=cand.headers).json()["grades"]}
    assert grades == {"backend": "middle", "qa": "junior"}
    emp = employer_with_company(client, "ООО Две категории")
    pid = public_id(client, cand)
    for spec in ("backend", "qa"):
        found = client.post("/api/v1/employer/candidates/search", headers=emp.headers,
                            json={"specialization": spec, "limit": 200}).json()["items"]
        assert any(r["candidate"]["candidate_id"] == pid for r in found), spec
    # карточка показывает категорию направления, в котором кандидата нашли, остальные — списком
    card = client.get("/api/v1/employer/candidates/%s" % pid, headers=emp.headers, params={"specialization": "backend"}).json()
    assert card["category"]["specialization"] == "backend"
    assert [c["specialization"] for c in card["other_categories"]] == ["qa"]
    card = client.get("/api/v1/employer/candidates/%s" % pid, headers=emp.headers).json()
    assert card["category"]["specialization"] == "qa"  # без параметра — основное направление (последний опрос)
