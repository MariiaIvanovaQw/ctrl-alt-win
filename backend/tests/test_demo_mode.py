"""Демо-режим для жюри: служебные методы, ссылки из писем, защита демо-учётных записей."""

from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.config import get_settings
from app.models import User
from app.services.mailer import send_email
from tests.conftest import PASSWORD, register, unique_email


def test_mailbox_shows_only_verification_letters(client, db):
    acc = register(client)
    other = unique_email("guardian")
    send_email(db, other, "Согласие на участие", "ссылка token=secret-guardian", kind="guardian_consent")
    db.commit()
    assert client.get("/api/v1/dev/mailbox", params={"to": other}).json() == []
    letters = client.get("/api/v1/dev/mailbox", params={"to": acc.email}).json()
    assert letters and all("Подтверждение" in m["subject"] for m in letters)
    assert client.get("/api/v1/dev/mailbox").status_code == 422, "без адреса чужие письма не отдаются"


def test_registration_returns_verification_link_in_demo_mode(client):
    email = unique_email("demo")
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "role": "candidate",
                                                   "consent_pd_processing": True}).json()
    link = r["dev_verification_link"]
    assert link and "token=" in link
    token = parse_qs(urlparse(link).query)["token"][0]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200


def test_dev_endpoints_are_closed_without_demo_mode(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    acc = register(client)
    assert client.get("/api/v1/dev/mailbox", params={"to": acc.email}).status_code == 404
    assert client.get("/api/v1/dev/demo-accounts").status_code == 404
    assert client.post("/api/v1/dev/me/reset-assessment", headers=acc.headers).status_code == 404
    assert client.get("/api/v1/reference").json()["demo_mode"] is False


def test_demo_accounts_do_not_expose_moderator_password(client):
    import json

    path = get_settings().data_dir / "demo_accounts.json"
    path.write_text(json.dumps({"password": "Demo12345", "candidates": [], "employers": [],
                                "moderator": {"email": "moderator@demo-fsp.ru", "password": "Secret-1", "note": "Модерация"}}),
                    encoding="utf-8")
    try:
        data = client.get("/api/v1/dev/demo-accounts").json()
    finally:
        path.unlink()
    assert data["moderator"]["email"] == "moderator@demo-fsp.ru" and "password" not in data["moderator"]
    assert "Secret-1" not in str(data)


def test_demo_accounts_cannot_be_deleted_or_change_password(client, db):
    acc = register(client)
    db.scalar(select(User).where(User.email == acc.email)).is_demo = True
    db.commit()
    r = client.delete("/api/v1/candidate/account", headers=acc.headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_account"
    r = client.post("/api/v1/auth/password/change", headers=acc.headers,
                    json={"current_password": PASSWORD, "new_password": "Other-pass-2"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_account"
