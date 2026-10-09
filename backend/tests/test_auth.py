"""Регистрация по почте, подтверждение, вход, токены в формате Keycloak, роли."""

import re

import jwt
import pytest
from fastapi.testclient import TestClient
from jwt import PyJWKSet
from sqlalchemy import select

from app.config import get_settings
from app.errors import AppError
from app.main import app
from tests.conftest import PASSWORD, last_mail, miss_first_lookup, register, unique_email


def test_login_requires_verified_email(client):
    email = unique_email("unverified")
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "role": "candidate", "consent_pd_processing": True})
    assert r.status_code == 201
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "email_not_verified"


def test_register_does_not_reveal_taken_email(client, monkeypatch):
    # вне демо-режима ответ одинаков; в демо-режиме ссылка подтверждения возвращается только новым адресам
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    acc = register(client)
    payload = {"email": acc.email, "password": PASSWORD, "role": "candidate", "consent_pd_processing": True}
    first = client.post("/api/v1/auth/register", json=dict(payload, email=unique_email("fresh")))
    again = client.post("/api/v1/auth/register", json=payload)
    assert again.status_code == first.status_code == 201
    assert again.json() == first.json() and first.json()["dev_verification_link"] is None
    assert "уже зарегистрирована" in last_mail(client, acc.email)


def test_registration_requires_consent_and_strong_password(client):
    r = client.post("/api/v1/auth/register", json={"email": unique_email("x"), "password": PASSWORD, "role": "candidate", "consent_pd_processing": False})
    assert r.json()["error"]["code"] == "consent_required"
    r = client.post("/api/v1/auth/register", json={"email": unique_email("x"), "password": "onlyletters", "role": "candidate", "consent_pd_processing": True})
    assert r.json()["error"]["code"] == "weak_password"


def test_verification_token_is_single_use(client):
    email = unique_email("once")
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "role": "candidate", "consent_pd_processing": True})
    token = re.search(r"token=([\w-]+)", last_mail(client, email)).group(1)
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.json()["error"]["code"] == "invalid_verification_token"


def test_wrong_password(client):
    acc = register(client)
    r = client.post("/api/v1/auth/login", json={"email": acc.email, "password": "Wrong-pass-1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_access_token_is_keycloak_compatible(client):
    acc = register(client, "employer")
    jwks = client.get("/idp/realms/platform/protocol/openid-connect/certs").json()
    discovery = client.get("/idp/realms/platform/.well-known/openid-configuration").json()
    token = acc.tokens["access_token"]
    kid = jwt.get_unverified_header(token)["kid"]
    key = PyJWKSet.from_dict(jwks)[kid].key
    claims = jwt.decode(token, key, algorithms=["RS256"], audience="talent-api", issuer=discovery["issuer"])
    assert claims["email"] == acc.email
    assert "employer" in claims["realm_access"]["roles"]


def test_refresh_rotation_and_reuse_detection(client):
    acc = register(client)
    old = acc.tokens["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 401 and r.json()["error"]["code"] == "refresh_token_reused"
    # повтор погашенного токена отзывает всю цепочку, включая новый токен
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new}).status_code == 401


def test_logout_revokes_refresh(client):
    acc = register(client)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": acc.tokens["refresh_token"]}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": acc.tokens["refresh_token"]}).status_code == 401


def test_roles_are_enforced(client):
    cand = register(client, "candidate")
    emp = register(client, "employer")
    assert client.get("/api/v1/employer/needs", headers=cand.headers).status_code == 403
    assert client.get("/api/v1/candidate/profile", headers=emp.headers).status_code == 403
    assert client.get("/api/v1/candidate/profile").status_code == 401
    r = client.get("/api/v1/candidate/profile", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_registration_only_with_ru_email(client):
    for email in ("user@gmail.com", "user@mail.com", "user@example.su", "user@почта.рф"):
        r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "role": "candidate",
                                                       "consent_pd_processing": True})
        assert r.status_code in (400, 422), email
        if r.status_code == 400:
            assert r.json()["error"]["code"] == "email_domain_not_allowed", email
    r = client.post("/api/v1/auth/register", json={"email": unique_email("ok").replace("test-fsp.ru", "Mail.RU"),
                                                   "password": PASSWORD, "role": "candidate", "consent_pd_processing": True})
    assert r.status_code == 201


def test_failed_logins_do_not_lock_owner_out_from_another_address(client):
    acc = register(client)
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": acc.email, "password": "Wrong-pass-1"})
    assert client.post("/api/v1/auth/login", json={"email": acc.email, "password": PASSWORD}).status_code == 429
    owner = TestClient(app, client=("203.0.113.7", 50000))
    assert owner.post("/api/v1/auth/login", json={"email": acc.email, "password": PASSWORD}).status_code == 200


def test_password_spraying_is_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_failures_per_ip", 5)
    sprayer = TestClient(app, client=("198.51.100.9", 50000))
    codes = [sprayer.post("/api/v1/auth/login", json={"email": unique_email("x"), "password": "Guess-1234"}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_parallel_refresh_with_one_token_is_detected_as_reuse(client):
    """Украденный и настоящий refresh-токен предъявлены одновременно: новую пару получает только один запрос."""
    from app.api.auth import RefreshIn, refresh
    from app.db import SessionLocal
    from app.models import RefreshToken
    from app.security.tokens import hash_token

    acc = register(client)
    token = acc.tokens["refresh_token"]
    racing = SessionLocal()
    # второй запрос уже прочитал токен, пока первый его гасил
    racing.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert first.status_code == 200
    with pytest.raises(AppError) as caught:
        refresh(RefreshIn(refresh_token=token), racing)
    racing.close()
    assert caught.value.code == "refresh_token_reused"
    # отозвана вся цепочка, включая пару, выданную первому запросу
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]})
    assert again.status_code == 401


def test_long_password_is_rejected_without_hashing(client):
    r = client.post("/api/v1/auth/login", json={"email": unique_email("x"), "password": "a" * 10_000})
    assert r.status_code == 422


def test_password_reset_and_change(client):
    acc = register(client)
    assert client.post("/api/v1/auth/password/forgot", json={"email": acc.email}).status_code == 200
    unknown = client.post("/api/v1/auth/password/forgot", json={"email": unique_email("nobody")})
    assert unknown.status_code == 200, "ответ одинаков для любого адреса"
    token = re.search(r"token=([\w-]+)", last_mail(client, acc.email)).group(1)
    r = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "New-pass-22"})
    assert r.status_code == 200
    # старые сессии завершены, ссылка одноразовая
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": acc.tokens["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "password": "New-pass-33"}).status_code == 400
    login = client.post("/api/v1/auth/login", json={"email": acc.email, "password": "New-pass-22"})
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    bad = client.post("/api/v1/auth/password/change", headers=headers, json={"current_password": "x", "new_password": "Pass-word-44"})
    assert bad.json()["error"]["code"] == "invalid_current_password"
    ok = client.post("/api/v1/auth/password/change", headers=headers,
                     json={"current_password": "New-pass-22", "new_password": "Pass-word-44"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/api/v1/auth/login", json={"email": acc.email, "password": "Pass-word-44"}).status_code == 200


def test_parallel_registration_with_same_email_gets_neutral_answer(client, monkeypatch):
    email = unique_email("race")
    body = {"email": email, "password": PASSWORD, "role": "candidate", "consent_pd_processing": True}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    miss_first_lookup(monkeypatch, "users.email")
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201 and r.json()["dev_verification_link"] is None
