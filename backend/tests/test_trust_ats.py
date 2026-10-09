"""Защита от недобросовестных работодателей и интеграция с ATS (вебхуки, JSON Resume)."""

import hashlib
import hmac
import json
import socket
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import Company, User, WebhookDelivery
from app.services import webhooks
from tests.conftest import create_need, employer_with_company, graded_candidate, invite, public_id, register


class Recorder:
    """ATS-приёмник для httpx.MockTransport."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": self.status < 300})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def test_webhook_signed_delivery_with_candidate_on_accept(client, db):
    emp = employer_with_company(client)
    r = client.post("/api/v1/employer/webhooks", headers=emp.headers, json={
        "url": "http://ats.local/hooks/talent", "events": ["invitation.accepted", "invitation.declined"]})
    assert r.status_code == 201, r.text
    hook = r.json()
    secret = hook["secret"]
    assert secret.startswith("whsec_")
    listed = client.get("/api/v1/employer/webhooks", headers=emp.headers).json()
    assert listed[0]["secret"] is None, "секрет показывается только при создании"

    cand = graded_candidate(client, "backend", "middle")
    inv = invite(client, emp, cand).json()
    client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=cand.headers, json={})

    ats = Recorder()
    assert webhooks.dispatch_due(db, ats.client()) >= 1
    request = next(r for r in ats.requests if r.headers["X-Talent-Event"] == "invitation.accepted")
    body = request.content
    expected = "sha256=" + hmac.new(secret.encode(), request.headers["X-Talent-Timestamp"].encode() + b"." + body,
                                    hashlib.sha256).hexdigest()
    assert hmac.compare_digest(request.headers["X-Talent-Signature"], expected)
    payload = json.loads(body)
    resume = payload["data"]["candidate"]
    assert resume["basics"]["phone"] == "+79000000001", "после принятия ATS получает контакты"
    assert resume["x-talent"]["category"]["level"] == "middle"
    deliveries = client.get("/api/v1/employer/webhooks/%s/deliveries" % hook["id"], headers=emp.headers).json()
    assert deliveries[0]["status"] == "delivered"


def test_employer_actions_reach_ats_and_review_blocks_inviting_applicants(client, db):
    """ATS узнаёт и о действиях самой компании; компания на проверке не приглашает, но может отказать."""

    emp = employer_with_company(client, "ООО Синхронизация")
    client.post("/api/v1/employer/webhooks", headers=emp.headers, json={
        "url": "http://ats.local/hooks/sync", "events": ["invitation.created", "application.invited", "application.rejected"]})
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    first, second = graded_candidate(client, "backend", "middle"), graded_candidate(client, "backend", "middle")
    assert invite(client, emp, first).status_code == 201
    app1 = client.post("/api/v1/candidate/applications", headers=first.headers, json={"need_id": need["id"]}).json()
    app2 = client.post("/api/v1/candidate/applications", headers=second.headers, json={"need_id": need["id"]}).json()
    respond = "/api/v1/employer/applications/%s/respond"
    assert client.post(respond % app1["id"], headers=emp.headers, json={"status": "invited"}).status_code == 200

    company = db.scalar(select(Company).where(Company.name == "ООО Синхронизация"))
    company.review_status = "on_review"
    db.commit()
    r = client.post(respond % app2["id"], headers=emp.headers, json={"status": "invited"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "company_on_review"
    assert client.post(respond % app2["id"], headers=emp.headers, json={"status": "rejected"}).status_code == 200

    ats = Recorder()
    webhooks.dispatch_due(db, ats.client())
    events = [r.headers["X-Talent-Event"] for r in ats.requests]
    assert events.count("invitation.created") == 1
    assert events.count("application.invited") == 1 and events.count("application.rejected") == 1


def test_webhook_retries_then_fails_and_manual_retry(client, db):
    emp = employer_with_company(client)
    hook = client.post("/api/v1/employer/webhooks", headers=emp.headers, json={
        "url": "http://ats.local/down", "events": ["invitation.viewed"]}).json()
    cand = graded_candidate(client, "qa", "junior", stack=["sql"])
    inv = invite(client, emp, cand).json()
    client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=cand.headers)

    ats = Recorder(status=500)
    webhooks.dispatch_due(db, ats.client())
    delivery = db.scalar(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == uuid.UUID(hook["id"])))
    assert delivery.status == "pending" and delivery.attempts == 1 and delivery.response_code == 500
    assert delivery.next_attempt_at > delivery.created_at, "повтор отложен"
    # исчерпываем попытки
    while delivery.status == "pending":
        webhooks.deliver(db, delivery, ats.client())
        db.commit()
    assert delivery.status == "failed"
    r = client.post("/api/v1/employer/webhooks/deliveries/%s/retry" % delivery.id, headers=emp.headers)
    assert r.json()["status"] == "pending"


def test_webhook_url_validation():
    for bad in ("ftp://ats.example.com/x", "http://127.0.0.1/hook", "https://10.1.2.3/hook", "https://localhost/hook",
                "https://169.254.169.254/latest/meta-data"):
        with pytest.raises(AppError):
            webhooks.validate_url(bad, allow_private=False)
    assert webhooks.validate_url("http://localhost:9000/hook", allow_private=True)


def test_unknown_event_rejected(client):
    emp = employer_with_company(client)
    r = client.post("/api/v1/employer/webhooks", headers=emp.headers, json={"url": "http://ats.local/x", "events": ["nope"]})
    assert r.status_code == 422


def test_json_resume_export_respects_contacts_rule(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    pid = public_id(client, cand)
    before = client.get("/api/v1/employer/candidates/%s/export" % pid, headers=emp.headers).json()
    assert "email" not in before["basics"] and "phone" not in before["basics"]
    assert before["x-talent"]["contacts_visible"] is False and before["skills"]
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    client.post("/api/v1/candidate/applications", headers=cand.headers, json={"need_id": need["id"]})
    after = client.get("/api/v1/employer/candidates/%s/export" % pid, headers=emp.headers).json()
    assert after["basics"]["phone"] == "+79000000001" and after["x-talent"]["contacts_reason"] == "candidate_applied"


def test_invitation_shows_company_trust_and_salary_warnings(client):
    cand = graded_candidate(client, "frontend", "junior", stack=["react"])
    emp = employer_with_company(client)
    inv = invite(client, emp, cand, salary_from=100000, salary_to=450000).json()
    seen = client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=cand.headers).json()
    assert seen["company_trust"]["invitations_sent"] == 1
    assert "Компания зарегистрирована недавно" in seen["company_trust"]["warnings"]
    assert any("широкая вилка" in w for w in seen["salary_warnings"])


def test_complaints_put_company_on_review_and_moderator_restores(client, db):
    emp = employer_with_company(client, "ООО Подозрительная")
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    for _ in range(3):
        cand = graded_candidate(client, "backend", "middle")
        inv = invite(client, emp, cand).json()
        r = client.post("/api/v1/candidate/invitations/%s/decline" % inv["id"], headers=cand.headers,
                        json={"reason": "suspicious", "comment": "Просили оплатить обучение"})
        assert r.status_code == 200
    company = client.get("/api/v1/employer/company", headers=emp.headers).json()
    assert company["review_status"] == "on_review" and company["complaints"] == 3

    blocked = invite(client, emp, graded_candidate(client, "backend", "middle"))
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "company_on_review"
    assert client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers).status_code == 403
    assert need["id"] not in {v["id"] for v in client.get("/api/v1/vacancies").json()["items"]}

    moderator = register(client, "candidate")
    user = db.scalar(select(User).where(User.email == moderator.email))
    user.role = "admin"
    db.commit()
    queue = client.get("/api/v1/admin/companies", headers=moderator.headers).json()
    target = next(c for c in queue if c["name"] == "ООО Подозрительная")
    assert len(client.get("/api/v1/admin/companies/%s/complaints" % target["id"], headers=moderator.headers).json()) == 3
    r = client.post("/api/v1/admin/companies/%s/review" % target["id"], headers=moderator.headers,
                    json={"decision": "restore", "comment": "Проверено, вакансия реальная"})
    assert r.json()["review_status"] == "active"
    assert invite(client, emp, graded_candidate(client, "backend", "middle")).status_code == 201
    # не модератор не видит очередь
    assert client.get("/api/v1/admin/companies", headers=emp.headers).status_code == 403


def test_complaint_on_vacancy_and_duplicates(client):
    emp = employer_with_company(client)
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    cand = register(client)
    body = {"vacancy_id": need["id"], "reason": "fake_vacancy", "comment": "Компания не отвечает"}
    assert client.post("/api/v1/candidate/complaints", headers=cand.headers, json=body).status_code == 201
    assert client.post("/api/v1/candidate/complaints", headers=cand.headers, json=body).json()["error"]["code"] == "complaint_exists"
    r = client.post("/api/v1/candidate/complaints", headers=cand.headers, json={"reason": "spam"})
    assert r.json()["error"]["code"] == "complaint_target_required"


def test_delivery_claimed_by_one_process_only(client, db):
    emp = employer_with_company(client)
    hook = client.post("/api/v1/employer/webhooks", headers=emp.headers, json={
        "url": "http://ats.local/race", "events": ["invitation.viewed"]}).json()
    delivery = WebhookDelivery(endpoint_id=uuid.UUID(hook["id"]), event="invitation.viewed", payload={"data": {}})
    db.add(delivery)
    db.commit()
    from app.db import SessionLocal

    with SessionLocal() as other:
        mine = db.get(WebhookDelivery, delivery.id)
        theirs = other.get(WebhookDelivery, delivery.id)
        assert webhooks._claim(db, mine) is True
        assert webhooks._claim(other, theirs) is False, "второй процесс не должен отправить то же событие"


def test_inn_checksum():
    from app.services.trust import inn_valid

    assert inn_valid("7707083893") and inn_valid("500100732259")
    assert not inn_valid("7707083894") and not inn_valid("500100732258") and not inn_valid("12345") and not inn_valid(None)


def test_voluntary_company_verification(client, db):
    emp = employer_with_company(client, "ООО Проверяемая")
    r = client.post("/api/v1/employer/company/verification", headers=emp.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "inn_invalid"
    body = {"name": "ООО Проверяемая", "inn": "7707083893", "industry": "fintech", "city": "Москва"}
    client.put("/api/v1/employer/company", headers=emp.headers, json=body)
    company = client.post("/api/v1/employer/company/verification", headers=emp.headers).json()
    assert company["verification_status"] == "requested" and company["verified"] is False

    moderator = register(client, "candidate")
    user = db.scalar(select(User).where(User.email == moderator.email))
    user.role = "admin"
    db.commit()
    queue = client.get("/api/v1/admin/verification-requests", headers=moderator.headers).json()
    target = next(c for c in queue if c["name"] == "ООО Проверяемая")
    assert target["inn"] == "7707083893"
    r = client.post("/api/v1/admin/companies/%s/verification" % target["id"], headers=moderator.headers, json={"approve": True})
    assert r.status_code == 200 and r.json()["trust"]["verified"] is True
    company = client.get("/api/v1/employer/company", headers=emp.headers).json()
    assert company["verified"] and company["verification_status"] == "verified"

    # метка относится к конкретному ИНН и названию
    client.put("/api/v1/employer/company", headers=emp.headers, json={**body, "name": "ООО Другая"})
    company = client.get("/api/v1/employer/company", headers=emp.headers).json()
    assert company["verified"] is False and company["verification_status"] == "none"


def test_suspended_company_cannot_message_and_blank_messages_rejected(client, db):

    emp = employer_with_company(client, "ООО Приостановленная")
    cand = graded_candidate(client, "backend", "middle")
    inv = invite(client, emp, cand).json()
    url = "/api/v1/employer/invitations/%s/messages" % inv["id"]
    assert client.post(url, headers=emp.headers, json={"body": "   "}).status_code == 422
    assert client.post(url, headers=emp.headers, json={"body": "Здравствуйте!"}).status_code in (200, 201)
    company = db.scalar(select(Company).where(Company.name == "ООО Приостановленная"))
    company.review_status = "on_review"
    db.commit()
    r = client.post(url, headers=emp.headers, json={"body": "Ещё вопрос"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "company_on_review"
    # кандидат по-прежнему может ответить или задать вопрос
    r = client.post("/api/v1/candidate/invitations/%s/messages" % inv["id"], headers=cand.headers, json={"body": "Что это за компания?"})
    assert r.status_code in (200, 201)


def test_one_candidate_cannot_suspend_company_with_vacancy_complaints(client):
    emp = employer_with_company(client, "ООО Честная")
    attacker = register(client)
    for _ in range(3):
        need = create_need(client, emp)
        client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
        r = client.post("/api/v1/candidate/complaints", headers=attacker.headers,
                        json={"vacancy_id": need["id"], "reason": "fake_vacancy"})
        assert r.status_code == 201
    assert client.get("/api/v1/employer/company", headers=emp.headers).json()["review_status"] == "active"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "100.64.0.1", "::ffff:127.0.0.1", "0.0.0.0"])
def test_webhook_target_rejects_internal_addresses(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(AppError):
        webhooks.resolve_target("https://ats.example.com/hook", allow_private=False)


def test_webhook_target_is_pinned_to_checked_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 8443))])
    target = webhooks.resolve_target("https://ats.example.com:8443/hooks/talent?x=1", allow_private=False)
    assert target.url == "https://93.184.216.34:8443/hooks/talent?x=1"
    assert target.headers == {"Host": "ats.example.com:8443"} and target.extensions == {"sni_hostname": "ats.example.com"}
