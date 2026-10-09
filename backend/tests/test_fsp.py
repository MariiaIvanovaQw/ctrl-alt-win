"""Привязка ФСП ID (OIDC + PKCE через встроенную заглушку) и вес достижений."""

import html
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models import FspAchievement, User
from app.services.fsp import achievement_weight, fsp_score
from tests.conftest import PASSWORD, register

BASE = "http://localhost:8000"


def _authorize(client, acc, fsp_id="FSP-100001"):
    r = client.post("/api/v1/candidate/fsp/link", headers=acc.headers, json={"consent": True})
    assert r.status_code == 200, r.text
    url = r.json()["authorization_url"]
    assert "code_challenge=" in url and "code_challenge_method=S256" in url and "state=" in url
    page = client.get(url.split(BASE, 1)[1])
    params = {k: html.unescape(v) for k, v in re.findall(r"name='(\w+)' value='([^']*)'", page.text)}
    params["fsp_id"] = fsp_id
    r = client.post("/mock-fsp/realms/fsp/login-actions/authenticate", data=params, follow_redirects=False)
    assert r.status_code in (302, 303)
    return r.headers["location"].split(BASE, 1)[1]


def test_link_requires_consent(client):
    acc = register(client)
    r = client.post("/api/v1/candidate/fsp/link", headers=acc.headers, json={"consent": False})
    assert r.status_code == 400


def _complete(client, acc, callback):
    """Возврат из ФСП ID уходит на фронтенд; привязку завершает запрос с токеном кандидата."""
    r = client.get(callback, follow_redirects=False)
    assert r.status_code == 303
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["fsp"] == ["confirm"]
    return client.post("/api/v1/candidate/fsp/link/complete", headers=acc.headers,
                       json={"code": query["fsp_code"][0], "state": query["fsp_state"][0]})


def test_link_flow_loads_achievements(client):
    acc = register(client)
    callback = _authorize(client, acc)
    r = _complete(client, acc, callback)
    assert r.status_code == 200, r.text
    status = client.get("/api/v1/candidate/fsp", headers=acc.headers).json()
    assert status["linked"] and status["fsp_id"] == "FSP-100001"
    assert status["achievements"]
    # повторное использование того же state отклоняется
    r = client.get(callback, follow_redirects=False)
    assert "fsp=error" in r.headers["location"]
    # отвязка удаляет снимок достижений
    assert client.delete("/api/v1/candidate/fsp", headers=acc.headers).status_code == 204
    status = client.get("/api/v1/candidate/fsp", headers=acc.headers).json()
    assert not status["linked"] and status["achievements"] == []


def test_link_started_in_two_tabs(client):
    """Привязку начали в двух вкладках: повтор с тем же ФСП ID — успех, с другим — понятный отказ, а не 500."""
    acc = register(client)
    first = _authorize(client, acc, "FSP-100001")
    second = _authorize(client, acc, "FSP-100001")
    third = _authorize(client, acc, "FSP-100003")
    assert _complete(client, acc, first).status_code == 200
    assert _complete(client, acc, second).status_code == 200
    r = _complete(client, acc, third)
    assert r.status_code == 409 and r.json()["error"]["code"] == "fsp_already_linked"
    assert client.get("/api/v1/candidate/fsp", headers=acc.headers).json()["fsp_id"] == "FSP-100001"
    assert client.delete("/api/v1/candidate/fsp", headers=acc.headers).status_code == 204


def test_foreign_link_session_cannot_be_completed(client):
    """CSRF при привязке: ссылку, начатую злоумышленником, жертва завершить к его профилю не может."""
    attacker = register(client)
    victim = register(client)
    callback = _authorize(client, attacker, "FSP-100003")
    r = _complete(client, victim, callback)
    assert r.status_code == 403 and r.json()["error"]["code"] == "fsp_state_foreign"
    assert client.get("/api/v1/candidate/fsp", headers=attacker.headers).json()["linked"] is False


def test_one_fsp_id_cannot_be_linked_twice(client):
    first = register(client)
    assert _complete(client, first, _authorize(client, first, "FSP-100002")).status_code == 200
    second = register(client)
    r = _complete(client, second, _authorize(client, second, "FSP-100002"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "fsp_id_taken"
    assert client.get("/api/v1/candidate/fsp", headers=second.headers).json()["linked"] is False


def test_callback_rejects_unknown_state(client):
    r = client.get("/api/v1/fsp/link/callback", params={"code": "<script>x</script>", "state": "nope"}, follow_redirects=False)
    assert r.status_code == 303 and "<script>" not in r.headers["location"] and "fsp=error" in r.headers["location"]


def _ach(**kw):
    data = dict(external_id="x", event_name="Соревнования", discipline="product", event_level="federal",
                result="winner", team_role="member", event_date=date(2026, 6, 1), verified=True)
    data.update(kw)
    return FspAchievement(**data)


def test_fsp_weight_properties():
    today = date(2026, 10, 1)
    base = achievement_weight(_ach(), today)
    # свежий результат весит больше, итог важнее участия
    assert achievement_weight(_ach(event_date=date(2022, 6, 1)), today) < base
    assert achievement_weight(_ach(result="participant"), today) < achievement_weight(_ach(result="prize"), today) < base
    # соревнования и дисциплины не ранжируются, роль в команде не даёт бонуса
    assert achievement_weight(_ach(event_level="local"), today) == base
    assert achievement_weight(_ach(discipline="robotics"), today) == base
    assert achievement_weight(_ach(team_role="captain"), today) == base
    assert fsp_score([_ach()], "backend", today)["score"] == fsp_score([_ach()], "qa", today)["score"]

    assert fsp_score([], "backend")["score"] == 0.0
    one = fsp_score([_ach()], "backend", today)["score"]
    three = fsp_score([_ach(external_id=str(i)) for i in range(3)], "backend", today)["score"]
    many = fsp_score([_ach(external_id=str(i)) for i in range(30)], "backend", today)["score"]
    assert 0 < one < three < many <= 1, "итог растёт с числом результатов и насыщается"
    # одними участиями профиль не набить: 30 онлайн-явок слабее одной победы
    attendance = fsp_score([_ach(external_id=str(i), result="participant") for i in range(30)], "backend", today)
    assert attendance["score"] < one
    assert attendance["stats"]["competitions"] == 30 and attendance["stats"]["podiums"] == 0
    assert fsp_score([_ach(verified=False)], "backend", today)["score"] == 0.0


def _login_via_fsp(client, fsp_id, consent=True):
    r = client.post("/api/v1/auth/fsp/start", json={"consent_pd_processing": consent, "consent_fsp_data": consent,
                                                    "redirect_after": "/candidate"})
    assert r.status_code == 200, r.text
    page = client.get(r.json()["authorization_url"].split(BASE, 1)[1])
    params = {k: html.unescape(v) for k, v in re.findall(r"name='(\w+)' value='([^']*)'", page.text)}
    params["fsp_id"] = fsp_id
    r = client.post("/mock-fsp/realms/fsp/login-actions/authenticate", data=params, follow_redirects=False)
    r = client.get(r.headers["location"].split(BASE, 1)[1], follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def test_login_via_fsp_id_creates_candidate_once(client):
    target = _login_via_fsp(client, "FSP-100004")
    assert "/login/fsp?" in target and "next=%2Fcandidate" in target
    code = re.search(r"code=([\w-]+)", target).group(1)
    tokens = client.post("/api/v1/auth/fsp/exchange", json={"code": code}).json()
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["role"] == "candidate" and me["email"] == "o.belova@demo-fsp.ru" and me["email_verified"]
    fsp = client.get("/api/v1/candidate/fsp", headers=headers).json()
    assert fsp["linked"] and fsp["fsp_id"] == "FSP-100004"
    # код одноразовый
    assert client.post("/api/v1/auth/fsp/exchange", json={"code": code}).status_code == 401
    # повторный вход находит тот же профиль по ФСП ID, согласия уже не нужны
    again = _login_via_fsp(client, "FSP-100004", consent=False)
    code2 = re.search(r"code=([\w-]+)", again).group(1)
    tokens2 = client.post("/api/v1/auth/fsp/exchange", json={"code": code2}).json()
    me2 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + tokens2["access_token"]}).json()
    assert me2["public_id"] == me["public_id"]


def test_login_via_fsp_id_requires_consent_for_new_profile(client):
    target = _login_via_fsp(client, "FSP-100003", consent=False)
    assert "/login?" in target and "reason=consent_required" in target


def test_link_returns_to_start_page_and_rejects_foreign_redirect(client):
    acc = register(client)
    bad = client.post("/api/v1/candidate/fsp/link", headers=acc.headers,
                      json={"consent": True, "redirect_after": "//evil.example"})
    assert bad.status_code == 422, "адрес другого сайта как путь возврата не принимается"
    url = client.post("/api/v1/candidate/fsp/link", headers=acc.headers,
                      json={"consent": True, "redirect_after": "/candidate/fsp"}).json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    r = client.get("/api/v1/fsp/link/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"].endswith("/candidate/fsp?fsp=cancelled"), "после отмены кандидат возвращается туда, откуда начал"


# Последним: тест привязывает участника FSP-100003, которого выше ждут свободным.
def test_unverified_account_takeover_via_fsp_login_is_blocked(client, db):
    victim_email = "d.orlov@demo-fsp.ru"  # почта участника FSP-100003 во встроенной заглушке
    r = client.post("/api/v1/auth/register", json={"email": victim_email, "password": PASSWORD, "role": "candidate",
                                                   "consent_pd_processing": True})
    assert r.status_code == 201  # злоумышленник занял адрес и не подтвердил его
    target = _login_via_fsp(client, "FSP-100003")
    code = re.search(r"code=([\w-]+)", target).group(1)
    assert client.post("/api/v1/auth/fsp/exchange", json={"code": code}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": victim_email, "password": PASSWORD})
    assert r.status_code == 401, "пароль, заданный посторонним до подтверждения, больше не действует"
    assert db.scalar(select(User).where(User.email == victim_email)).password_hash is None
