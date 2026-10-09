"""
Чужие записи недоступны: второй кандидат и второй работодатель получают
404 (или 403) на каждом методе с идентификатором чужой записи — и на
чтение, и на изменение.
"""

import uuid

from app.db import SessionLocal
from app.models import EmployerTask
from tests.conftest import create_need, employer_with_company, graded_candidate, register, survey

INVITE = {
    "title": "Python-разработчик",
    "description": "Платёжный сервис, команда из шести человек, гибридный формат работы",
    "salary_from": 250000,
    "salary_to": 320000,
    "contact_method": "hr@example.ru",
}
DENIED = (403, 404)


def test_records_of_others_are_not_reachable(client):
    owner = graded_candidate(client, "backend", "middle")
    stranger = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client, "ООО Владелец")
    other_emp = employer_with_company(client, "ООО Чужак")
    pid = client.get("/api/v1/auth/me", headers=owner.headers).json()["public_id"]

    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    inv = client.post("/api/v1/employer/invitations", headers=emp.headers, json={**INVITE, "candidate_id": pid}).json()
    application = client.post("/api/v1/candidate/applications", headers=owner.headers, json={"need_id": need["id"]}).json()
    selection = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={}).json()
    # кандидату выдаётся одно задание за раз: убираем активные задания других тестов
    with SessionLocal() as db:
        for t in db.query(EmployerTask).filter(EmployerTask.active.is_(True)):
            t.active = False
        db.commit()
    task = client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Подход к повторам", "kind": "approach", "specialization": "backend",
        "body": "Как безопасно повторить платёж после таймаута шлюза?"}).json()
    webhook = client.post("/api/v1/employer/webhooks", headers=emp.headers, json={
        "url": "https://ats.example.ru/hook", "events": ["invitation.accepted"]}).json()
    assignment = next(t for t in client.get("/api/v1/candidate/tasks", headers=owner.headers).json()
                      if t["task"]["title"] == "Подход к повторам")
    # задание выдано владельцу; дальше не выдаётся, чтобы не мешать другим тестам
    with SessionLocal() as db:
        db.get(EmployerTask, uuid.UUID(task["id"])).active = False
        db.commit()
    attempt_id = client.get("/api/v1/candidate/assessment/status", headers=owner.headers).json()["attempts"][0]["id"]

    # другой кандидат
    s = stranger.headers
    for method, url, body in [
        ("GET", "/api/v1/candidate/assessment/attempts/%s" % attempt_id, None),
        ("PUT", "/api/v1/candidate/assessment/attempts/%s/answers/0" % attempt_id, {"value": "A"}),
        ("POST", "/api/v1/candidate/assessment/attempts/%s/signals" % attempt_id, {"kind": "copy"}),
        ("POST", "/api/v1/candidate/assessment/attempts/%s/finish" % attempt_id, None),
        ("POST", "/api/v1/dev/me/attempts/%s/autofill" % attempt_id, {"answer_as": "senior"}),
        ("GET", "/api/v1/candidate/invitations/%s" % inv["id"], None),
        ("POST", "/api/v1/candidate/invitations/%s/accept" % inv["id"], {}),
        ("POST", "/api/v1/candidate/invitations/%s/decline" % inv["id"], {"reason": "salary"}),
        ("POST", "/api/v1/candidate/invitations/%s/revoke-contacts" % inv["id"], None),
        ("GET", "/api/v1/candidate/invitations/%s/messages" % inv["id"], None),
        ("POST", "/api/v1/candidate/invitations/%s/messages" % inv["id"], {"body": "Чужое сообщение"}),
        ("GET", "/api/v1/candidate/applications/%s/messages" % application["id"], None),
        ("POST", "/api/v1/candidate/applications/%s/messages" % application["id"], {"body": "Чужое сообщение"}),
        ("POST", "/api/v1/candidate/applications/%s/revoke-contacts" % application["id"], None),
        ("POST", "/api/v1/candidate/applications/%s/withdraw" % application["id"], None),
        ("POST", "/api/v1/candidate/tasks/%s/submit" % assignment["id"], {"text": "Чужое решение задания, длинный текст"}),
    ]:
        r = client.request(method, url, headers=s, json=body)
        assert r.status_code in DENIED, (method, url, r.status_code, r.text[:200])

    # другой работодатель
    o = other_emp.headers
    for method, url, body in [
        ("GET", "/api/v1/employer/needs/%s" % need["id"], None),
        ("PATCH", "/api/v1/employer/needs/%s" % need["id"], {"title": "Взлом"}),
        ("POST", "/api/v1/employer/needs/%s/publish" % need["id"], None),
        ("POST", "/api/v1/employer/needs/%s/unpublish" % need["id"], None),
        ("POST", "/api/v1/employer/needs/%s/close" % need["id"], None),
        ("GET", "/api/v1/employer/needs/%s/test-preview" % need["id"], None),
        ("GET", "/api/v1/employer/needs/%s/selections" % need["id"], None),
        ("POST", "/api/v1/employer/needs/%s/selections" % need["id"], {}),
        ("GET", "/api/v1/employer/selections/%s" % selection["id"], None),
        ("POST", "/api/v1/employer/selections/%s/refine" % selection["id"], {}),
        ("GET", "/api/v1/employer/invitations/%s" % inv["id"], None),
        ("POST", "/api/v1/employer/invitations/%s/withdraw" % inv["id"], None),
        ("GET", "/api/v1/employer/invitations/%s/messages" % inv["id"], None),
        ("POST", "/api/v1/employer/invitations/%s/messages" % inv["id"], {"body": "Чужое сообщение"}),
        ("GET", "/api/v1/employer/applications/%s" % application["id"], None),
        ("GET", "/api/v1/employer/applications/%s/messages" % application["id"], None),
        ("POST", "/api/v1/employer/applications/%s/messages" % application["id"], {"body": "Чужое сообщение"}),
        ("POST", "/api/v1/employer/applications/%s/respond" % application["id"], {"status": "invited"}),
        ("GET", "/api/v1/employer/tasks/%s/submissions" % task["id"], None),
        ("POST", "/api/v1/employer/tasks/submissions/%s/review" % assignment["id"], {"score": 5}),
        ("PATCH", "/api/v1/employer/webhooks/%s" % webhook["id"], {"active": False}),
        ("POST", "/api/v1/employer/webhooks/%s/rotate-secret" % webhook["id"], None),
        ("POST", "/api/v1/employer/webhooks/%s/ping" % webhook["id"], None),
        ("GET", "/api/v1/employer/webhooks/%s/deliveries" % webhook["id"], None),
        ("DELETE", "/api/v1/employer/webhooks/%s" % webhook["id"], None),
    ]:
        r = client.request(method, url, headers=o, json=body)
        assert r.status_code in DENIED, (method, url, r.status_code, r.text[:200])

    # контакты кандидата открыты только компании, которой он откликнулся
    card = client.get("/api/v1/employer/candidates/%s" % pid, headers=o).json()
    assert card["contacts"] is None and not card["contacts_visible"]
    resume = client.get("/api/v1/employer/candidates/%s/export" % pid, headers=o).json()
    assert "email" not in str(resume.get("basics", {})).lower() or not resume["basics"].get("email")

    # роли: кандидат не пользуется методами работодателя и модератора
    for url in ("/api/v1/employer/needs", "/api/v1/admin/companies", "/api/v1/admin/verification-requests"):
        assert client.get(url, headers=s).status_code == 403
    assert client.get("/api/v1/candidate/profile", headers=o).status_code == 403



def test_unverified_or_unsurveyed_candidate_cannot_reach_others_attempt(client):
    a = register(client)
    survey(client, a, "qa", "junior")
    attempt = client.post("/api/v1/candidate/assessment/attempts", headers=a.headers,
                          json={"specialization": "qa", "level": "junior"}).json()
    b = register(client)
    assert client.get("/api/v1/candidate/assessment/attempts/%s" % attempt["id"], headers=b.headers).status_code == 404
