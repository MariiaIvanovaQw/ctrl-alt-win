"""Кандидаты 14–17 лет: согласие законного представителя, видимость и ограничения предложений."""

import re

from app.services.minors import today_local
from tests.conftest import (
    create_need,
    employer_with_company,
    last_mail,
    pass_test,
    publish_candidate,
    register,
    survey,
    unique_email,
)

INVITE = {
    "title": "Стажёр-разработчик",
    "description": "Стажировка на летние каникулы: помощь команде с тестами и документацией, 4 часа в день",
    "salary_from": 30000,
    "salary_to": 40000,
    "contact_method": "hr@example.ru",
}


def _years_ago(years: int) -> str:
    today = today_local()
    return today.replace(year=today.year - years).isoformat()


def _minor_with_grade(client):
    acc = register(client)
    client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(16), "full_name": "Пётр Школьников"})
    survey(client, acc, "backend", "junior", birth_date=None)
    pass_test(client, acc, "backend", "junior")
    return acc


def _guardian_link(client, acc, email="parent-%s@test-fsp.ru"):
    email = email % acc.email.split("@")[0]
    r = client.post("/api/v1/candidate/guardian", headers=acc.headers, json={"full_name": "Мария Школьникова", "email": email})
    assert r.status_code == 200, r.text
    assert r.json()["guardian"]["status"] == "pending"
    return re.search(r"token=([\w-]+)", last_mail(client, email)).group(1)


def test_age_limits(client):
    acc = register(client)
    r = client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(12)})
    assert r.status_code == 422
    assert client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": "2999-01-01"}).status_code == 422
    profile = client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(17)}).json()
    assert profile["minor"] is True and profile["age"] == 17
    adult = client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(18)}).json()
    assert adult["minor"] is False


def test_minor_is_hidden_until_guardian_consents(client):
    acc = _minor_with_grade(client)
    r = client.post("/api/v1/candidate/consents", headers=acc.headers, json={"kind": "profile_publication", "granted": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "guardian_consent_required"

    token = _guardian_link(client, acc)
    view = client.get("/api/v1/guardian-consent", params={"token": token}).json()
    assert view["candidate_name"] == "Пётр Школьников" and view["candidate_age"] == 16 and view["status"] == "pending"
    assert client.post("/api/v1/guardian-consent", json={"token": token, "decision": "grant"}).json()["status"] == "granted"

    publish_candidate(client, acc)
    emp = employer_with_company(client, "ООО Стажировки")
    pid = client.get("/api/v1/auth/me", headers=acc.headers).json()["public_id"]
    card = client.get("/api/v1/employer/candidates/%s" % pid, headers=emp.headers).json()
    assert card["minor"] is True and card["minor_note"]
    assert "birth_date" not in card

    # отзыв представителем сразу скрывает профиль
    assert client.post("/api/v1/guardian-consent", json={"token": token, "decision": "revoke"}).json()["status"] == "revoked"
    assert client.get("/api/v1/employer/candidates/%s" % pid, headers=emp.headers).status_code == 404


def test_offers_to_minor_must_be_suitable(client):
    acc = _minor_with_grade(client)
    token = _guardian_link(client, acc)
    client.post("/api/v1/guardian-consent", json={"token": token, "decision": "grant"})
    publish_candidate(client, acc)
    pid = client.get("/api/v1/auth/me", headers=acc.headers).json()["public_id"]
    emp = employer_with_company(client, "ООО Каникулы")

    r = client.post("/api/v1/employer/invitations", headers=emp.headers, json={**INVITE, "candidate_id": pid})
    assert r.status_code == 409 and r.json()["error"]["code"] == "minor_offer_not_suitable"
    r = client.post("/api/v1/employer/invitations", headers=emp.headers,
                    json={**INVITE, "candidate_id": pid, "suitable_for_minors": True})
    assert r.status_code == 201 and r.json()["suitable_for_minors"] is True

    regular = create_need(client, emp, level="junior")
    client.post("/api/v1/employer/needs/%s/publish" % regular["id"], headers=emp.headers)
    r = client.post("/api/v1/candidate/applications", headers=acc.headers, json={"need_id": regular["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "minor_offer_not_suitable"
    internship = create_need(client, emp, level="junior", title="Стажёр на лето", suitable_for_minors=True)
    client.post("/api/v1/employer/needs/%s/publish" % internship["id"], headers=emp.headers)
    assert client.post("/api/v1/candidate/applications", headers=acc.headers, json={"need_id": internship["id"]}).status_code == 201
    recommended = client.get("/api/v1/candidate/vacancies/recommended", headers=acc.headers).json()
    assert recommended["minor"] and all(v["suitable_for_minors"] for v in recommended["items"])


def test_birth_date_after_publication_hides_profile(client):
    acc = register(client)
    publish_candidate(client, acc)
    survey(client, acc, "qa", "junior")
    pass_test(client, acc, "qa", "junior")
    client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(15)})
    consents = {c["kind"]: c["granted"] for c in client.get("/api/v1/candidate/consents", headers=acc.headers).json()}
    assert consents["profile_publication"] is False


def test_guardian_email_rules(client):
    acc = register(client)
    client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": _years_ago(16)})
    own = client.post("/api/v1/candidate/guardian", headers=acc.headers, json={"full_name": "Сам Себе", "email": acc.email})
    assert own.json()["error"]["code"] == "guardian_email_is_own"
    foreign = client.post("/api/v1/candidate/guardian", headers=acc.headers, json={"full_name": "Мама Иванова", "email": "mama@gmail.com"})
    assert foreign.json()["error"]["code"] == "email_domain_not_allowed"
    adult = register(client)
    r = client.post("/api/v1/candidate/guardian", headers=adult.headers, json={"full_name": "Мама Иванова", "email": "mama@test-fsp.ru"})
    assert r.json()["error"]["code"] == "not_minor"


def test_minor_cannot_accept_after_guardian_revoked(client):
    acc = _minor_with_grade(client)
    token = _guardian_link(client, acc)
    client.post("/api/v1/guardian-consent", json={"token": token, "decision": "grant"})
    publish_candidate(client, acc)
    pid = client.get("/api/v1/auth/me", headers=acc.headers).json()["public_id"]
    emp = employer_with_company(client, "ООО Отзыв")
    inv = client.post("/api/v1/employer/invitations", headers=emp.headers,
                      json={**INVITE, "candidate_id": pid, "suitable_for_minors": True}).json()
    client.post("/api/v1/guardian-consent", json={"token": token, "decision": "revoke"})
    r = client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=acc.headers, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "guardian_consent_required"


def test_survey_requires_birth_date(client):
    acc = register(client)
    r = client.post("/api/v1/candidate/survey", headers=acc.headers, json={"specialization": "qa", "self_level": "junior"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "birth_date_required"
    survey(client, acc, "qa", "junior")
    profile = client.get("/api/v1/candidate/profile", headers=acc.headers).json()
    assert profile["birth_date"] and profile["minor"] is False
    # стереть дату нельзя — иначе несовершеннолетний обошёл бы согласие представителя
    r = client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": None})
    assert r.status_code == 400 and r.json()["error"]["code"] == "birth_date_required"
    assert client.patch("/api/v1/candidate/profile", headers=acc.headers, json={"birth_date": "1996-01-02"}).status_code == 200


def test_fourteen_year_old_can_test_but_not_be_shown_or_apply(client):
    acc = register(client)
    today = today_local()
    birth = today.replace(year=today.year - 14).isoformat()
    survey(client, acc, "frontend", "junior", birth_date=birth)
    assert client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers,
                       json={"specialization": "frontend", "level": "junior"}).status_code == 201
    r = client.post("/api/v1/candidate/consents", headers=acc.headers, json={"kind": "profile_publication", "granted": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_young_for_work"


def test_revoked_guardian_link_cannot_be_reused(client):
    acc = _minor_with_grade(client)
    token = _guardian_link(client, acc)
    assert client.post("/api/v1/guardian-consent", json={"token": token, "decision": "grant"}).json()["status"] == "granted"
    revoked = client.post("/api/v1/guardian-consent", json={"token": token, "decision": "revoke"}).json()
    assert revoked["status"] == "revoked" and revoked["link_closed"] is True
    r = client.post("/api/v1/guardian-consent", json={"token": token, "decision": "grant"})
    assert r.status_code == 404, "отозванное согласие не включается старой ссылкой"


def test_guardian_request_returns_link_in_demo_mode(client):
    acc = register(client)
    today = today_local()
    client.patch("/api/v1/candidate/profile", headers=acc.headers,
                 json={"birth_date": today.replace(year=today.year - 16).isoformat()})
    r = client.post("/api/v1/candidate/guardian", headers=acc.headers,
                    json={"full_name": "Мария Иванова", "email": unique_email("parent")}).json()
    assert r["dev_link"] and "/guardian-consent?token=" in r["dev_link"]
