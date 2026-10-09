"""Антиплагиат: совпадение неверных ответов в тесте и сходство ответов «предложите подход»."""

import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Attempt, AttemptAnswer, EmployerTask, User
from app.services.integrity import canonical_answer, text_overlap
from tests.conftest import employer_with_company, graded_candidate, register, survey

QA = {"specialization": "qa", "level": "junior"}


def _start(client, acc) -> str:
    survey(client, acc, "qa", "junior")
    r = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers, json=QA)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _copy_test(source_id: str, target_id: str) -> list[dict]:
    """Делает тест второй попытки таким же, как у первой (те же задания, варианты и порядок ответов)."""
    with SessionLocal() as s:
        src, dst = s.get(Attempt, uuid.UUID(source_id)), s.get(Attempt, uuid.UUID(target_id))
        dst.items, dst.keys, dst.client_items = src.items, src.keys, src.client_items
        rows = {r.position: r for r in s.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == src.id))}
        for r in s.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == dst.id)):
            r.item_id, r.variant_id = rows[r.position].item_id, rows[r.position].variant_id
            r.competency, r.difficulty = rows[r.position].competency, rows[r.position].difficulty
        s.commit()
        return list(src.keys)


def _answer_wrong(client, acc, attempt_id: str, keys: list[dict], pick: int, free: str) -> dict:
    url = "/api/v1/candidate/assessment/attempts/%s" % attempt_id
    for position, key in enumerate(keys):
        if key.get("options_count"):
            wrong = [x for x in "ABCDEF"[: key["options_count"]] if x not in key["correct_letters"]]
            value = wrong[pick % len(wrong)]
            if key["validation_type"] == "multiple_choice":
                value = [value]
        else:
            value = free
        assert client.put("%s/answers/%d" % (url, position), headers=acc.headers, json={"value": value}).status_code == 200
    return client.post(url + "/finish", headers=acc.headers).json()["result"]


def test_canonical_answer_ignores_option_order():
    key = {"options_count": 3, "correct_letters": ["A"]}
    first = {"options": [{"id": "A", "text": "верно"}, {"id": "B", "text": "ловушка"}, {"id": "C", "text": "другое"}]}
    second = {"options": [{"id": "A", "text": "другое"}, {"id": "B", "text": "верно"}, {"id": "C", "text": "ловушка"}]}
    assert canonical_answer(first, key, "B") == canonical_answer(second, key, "C")
    assert canonical_answer(first, key, "B") != canonical_answer(second, key, "B")
    assert canonical_answer({}, {"options_count": 0}, " 2,50 ") == canonical_answer({}, {"options_count": 0}, "2.5")


def test_identical_wrong_answers_are_flagged_for_both(client):
    a, b, c = register(client), register(client), register(client)
    first, second, third = _start(client, a), _start(client, b), _start(client, c)
    keys = _copy_test(first, second)
    _copy_test(first, third)

    _answer_wrong(client, a, first, keys, pick=0, free="ответ наугад")
    copied = _answer_wrong(client, b, second, keys, pick=0, free="ответ наугад")
    flag = next(f for f in copied["flags"] if f["code"] == "answer_overlap")
    assert "одинаковых неверных ответов" in flag["message"]
    assert set(flag) == {"code", "message"}, "кандидат не видит, с чьей попыткой совпадение"
    with SessionLocal() as s:
        earlier = s.get(Attempt, uuid.UUID(first))
        assert any(f["code"] == "answer_overlap" for f in earlier.flags), "признак ставится обеим попыткам"

    # те же задания, но свои ошибки — признака нет
    own = _answer_wrong(client, c, third, keys, pick=1, free="другой ответ")
    assert all(f["code"] != "answer_overlap" for f in own["flags"])
    assert own["applied"]["action"] == "not_confirmed", "признак не влияет на грейд"


def test_copied_approach_answer_is_flagged_for_employer(client):
    emp = employer_with_company(client, "ООО Антиплагиат")
    r = client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Подход к кэшированию", "kind": "approach", "specialization": "backend",
        "body": "Каталог товаров отвечает медленно под нагрузкой. Как бы вы это исправили?"})
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]
    original = ("Сначала сниму профиль запросов и найду самые частые чтения каталога. Добавлю кэш в Redis "
                "с инвалидацией по событию изменения товара, а для списков — короткий TTL и прогрев после деплоя.")
    texts = [
        original,
        original + " Ещё проверю индексы в PostgreSQL.",
        "Посмотрю метрики и трассировку, вынесу тяжёлые отчёты в отдельную реплику, "
        "добавлю пагинацию по курсору и ограничу размер ответа API, чтобы не тащить лишние поля.",
    ]
    try:
        for text in texts:
            cand = graded_candidate(client, "backend", "middle")
            tasks = client.get("/api/v1/candidate/tasks", headers=cand.headers).json()
            mine = next(t for t in tasks if t["task"]["title"] == "Подход к кэшированию")
            r = client.post("/api/v1/candidate/tasks/%s/submit" % mine["id"], headers=cand.headers, json={"text": text})
            assert r.status_code == 200, r.text
    finally:
        # задание больше не выдаётся: другие тесты ждут свои задания у кандидатов backend
        with SessionLocal() as s:
            s.get(EmployerTask, uuid.UUID(task_id)).active = False
            s.commit()
    subs = client.get("/api/v1/employer/tasks/%s/submissions" % task_id, headers=emp.headers).json()["submissions"]
    flagged = [s for s in subs if s["similar_to"]]
    assert len(flagged) == 2 and all(s["similar_to"]["share"] >= 0.6 for s in flagged)
    ids = {s["candidate_id"] for s in flagged}
    assert all(s["similar_to"]["candidate_id"] in ids for s in flagged), "указан кандидат с похожим ответом"


def test_text_overlap_needs_enough_text():
    assert text_overlap("да, кэш", "да, кэш") == 0.0
    phrase = "добавлю кэш в redis с инвалидацией по событию изменения товара и прогревом после деплоя"
    assert text_overlap(phrase, phrase.upper()) == 1.0


def test_employer_sees_flags_in_card(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client, "ООО Карточка")
    pid = client.get("/api/v1/auth/me", headers=cand.headers).json()["public_id"]
    with SessionLocal() as s:
        user_id = s.scalar(select(User.id).where(User.public_id == pid))
        attempt = s.scalar(select(Attempt).where(Attempt.user_id == user_id))
        attempt.flags = [{"code": "answer_overlap", "matches": 9, "shared": 9, "message": "Совпадение ошибок"}]
        s.commit()
    card = client.get("/api/v1/employer/candidates/%s" % pid, headers=emp.headers).json()
    assert card["test"]["flags"] == [{"code": "answer_overlap", "message": "Совпадение ошибок"}]
