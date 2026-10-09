"""
Общие фикстуры. Каталог данных задаётся до импорта приложения: движок БД
и ключ подписи токенов создаются при импорте и должны смотреть во
временный каталог, а не в data/ разработчика.
"""

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass

DATA_DIR = tempfile.mkdtemp(prefix="fsp-tests-")
os.environ["APP_DATA_DIR"] = DATA_DIR
os.environ["APP_ENV"] = "dev"
os.environ["APP_DEMO_MODE"] = "true"  # служебные методы /dev/* (экспресс-режим, сброс) проверяются тестами
os.environ["APP_WEBHOOK_ALLOW_PRIVATE_HOSTS"] = "true"  # приёмник вебхуков в тестах — httpx.MockTransport
os.environ["APP_AUTH_MODE"] = "local"
os.environ["APP_FSP_MODE"] = "inprocess"
# По умолчанию — SQLite во временном каталоге. Прогон на PostgreSQL:
#   TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:port/db python -m pytest
# База очищается перед прогоном, поэтому указывайте отдельную тестовую базу.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
os.environ["APP_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_WEBHOOK_DISPATCH_INTERVAL_SECONDS"] = "0"  # диспетчер вебхуков вызывается в тестах явно

if TEST_DATABASE_URL.startswith("postgresql"):
    from sqlalchemy import create_engine, text

    _engine = create_engine(TEST_DATABASE_URL)
    with _engine.begin() as _conn:
        _conn.execute(text("DROP SCHEMA public CASCADE"))
        _conn.execute(text("CREATE SCHEMA public"))
    _engine.dispose()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Attempt, OutboxEmail  # noqa: E402
from app.services.ratelimit import login_limiter, password_limiter, register_limiter  # noqa: E402

PASSWORD = "Test-pass-1"
ADULT_BIRTH_DATE = "1995-05-17"


@dataclass
class Account:
    email: str
    headers: dict
    tokens: dict


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_limits():
    login_limiter.clear()
    register_limiter.clear()
    password_limiter.clear()
    from app.services.matching import reset_category_cache

    reset_category_cache()


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def unique_email(prefix: str) -> str:
    return "%s-%s@test-fsp.ru" % (prefix, uuid.uuid4().hex[:10])


def last_mail(client, email: str) -> str:
    """Последнее письмо на адрес — прямо из копий писем в базе (как увидел бы его получатель)."""
    from sqlalchemy import select

    with SessionLocal() as s:
        mail = s.scalar(select(OutboxEmail).where(OutboxEmail.to_email == email.lower()).order_by(OutboxEmail.created_at.desc()))
    assert mail is not None, "нет писем на %s" % email
    return mail.body


def register(client, role: str = "candidate", email: str | None = None) -> Account:
    email = email or unique_email(role)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "role": role, "consent_pd_processing": True},
    )
    assert r.status_code == 201, r.text
    token = re.search(r"token=([\w-]+)", last_mail(client, email)).group(1)
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    tokens = r.json()
    return Account(email, {"Authorization": "Bearer " + tokens["access_token"]}, tokens)


def publish_candidate(client, acc: Account, **profile) -> None:
    data = {
        "full_name": "Петров Пётр Петрович",
        "city": "Москва",
        "phone": "+79000000001",
        "salary_expectation": 220000,
        "work_formats": ["remote", "hybrid"],
        "stack": ["python", "postgresql", "redis"],
    }
    data.update(profile)
    assert client.patch("/api/v1/candidate/profile", headers=acc.headers, json=data).status_code == 200
    r = client.post("/api/v1/candidate/consents", headers=acc.headers, json={"kind": "profile_publication", "granted": True})
    assert r.status_code in (200, 201), r.text


def survey(client, acc: Account, spec: str = "backend", level: str = "middle", birth_date: str | None = ADULT_BIRTH_DATE) -> None:
    """Опрос; birth_date=None — дата рождения уже указана в профиле (тесты несовершеннолетних)."""
    body = {"industry": "fintech", "specialization": spec, "self_level": level, "experience_years": 3,
            "stack": ["python"], "roles": ["developer"], "work_formats": ["remote"]}
    if birth_date:
        body["birth_date"] = birth_date
    r = client.post("/api/v1/candidate/survey", headers=acc.headers, json=body)
    assert r.status_code == 201, r.text


def pass_test(client, acc: Account, spec: str = "backend", level: str = "middle", correct: bool = True) -> dict:
    """Проходит тест: верные ответы берутся из ключей попытки в БД."""
    r = client.post("/api/v1/candidate/assessment/attempts", headers=acc.headers, json={"specialization": spec, "level": level})
    assert r.status_code == 201, r.text
    attempt = r.json()
    with SessionLocal() as s:
        keys = s.get(Attempt, uuid.UUID(attempt["id"])).keys
    for key, item in zip(keys, attempt["items"], strict=True):
        if correct:
            value = key["correct_letters"] if len(key.get("correct_letters", [])) > 1 else (
                key["correct_letters"][0] if "correct_letters" in key else key["correct_values"][0])
        else:
            value = None
        r = client.put(
            "/api/v1/candidate/assessment/attempts/%s/answers/%d" % (attempt["id"], item["position"]),
            headers=acc.headers,
            json={"value": value},
        )
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/candidate/assessment/attempts/%s/finish" % attempt["id"], headers=acc.headers)
    assert r.status_code == 200, r.text
    return r.json()


def graded_candidate(client, spec: str = "backend", level: str = "middle", **profile) -> Account:
    acc = register(client, "candidate")
    publish_candidate(client, acc, **profile)
    survey(client, acc, spec, level)
    result = pass_test(client, acc, spec, level)
    assert result["result"]["applied"]["action"] == "assigned", result["result"]["applied"]
    return acc


def employer_with_company(client, name: str = "ООО Тест") -> Account:
    acc = register(client, "employer")
    r = client.put("/api/v1/employer/company", headers=acc.headers, json={"name": name, "industry": "fintech", "city": "Москва"})
    assert r.status_code == 200, r.text
    return acc


def create_need(client, emp: Account, **fields) -> dict:
    data = {
        "title": "Python-разработчик",
        "specialization": "backend",
        "level": "middle",
        "description": "Платёжный сервис: FastAPI, PostgreSQL, Redis, идемпотентность и гонки",
        "stack": ["python", "postgresql"],
        "work_format": "remote",
        "salary_from": 200000,
        "salary_to": 300000,
    }
    data.update(fields)
    r = client.post("/api/v1/employer/needs", headers=emp.headers, json=data)
    assert r.status_code == 201, r.text
    return r.json()


def public_id(client, acc: Account) -> str:
    """Псевдоним кандидата, под которым его видят работодатели."""
    return client.get("/api/v1/auth/me", headers=acc.headers).json()["public_id"]


INVITATION = {
    "title": "Python-разработчик",
    "description": "Приглашаем в команду платёжного сервиса, работа удалённо",
    "salary_from": 230000,
    "salary_to": 290000,
    "contact_method": "hr@example.com",
}


def invite(client, emp: Account, cand: Account, **extra):
    """Приглашение кандидату с обязательными полями; extra дополняет или заменяет их."""
    return client.post("/api/v1/employer/invitations", headers=emp.headers,
                       json=dict(INVITATION, candidate_id=public_id(client, cand), **extra))


def miss_first_lookup(monkeypatch, marker: str) -> None:
    """Первый поиск по `marker` ничего не находит — как у параллельного запроса, который не видел запись."""
    from sqlalchemy.orm import Session

    real = Session.scalar

    def scalar(self, statement, *args, **kwargs):
        if marker in str(statement):
            monkeypatch.setattr(Session, "scalar", real)
            return None
        return real(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", scalar)

