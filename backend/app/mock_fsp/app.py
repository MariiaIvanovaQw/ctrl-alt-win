"""
Заглушка ФСП ID и реестра достижений.

Повторяет внешний интерфейс Keycloak (discovery, JWKS, authorization code
с PKCE, client_credentials) и простой REST реестра, чтобы платформа
работала с ФСП так же, как будет работать с настоящим ФСП ID. Монтируется
в основное приложение по адресу /mock-fsp. Только для разработки и демо.
"""

import base64
import hashlib
import html
import secrets
import time
import uuid
from functools import lru_cache
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.mock_fsp.data import participants
from app.security.keyfile import load_or_create_rsa
from app.services.fsp_gateway import mock_public_base

mock_app = FastAPI(
    title="Заглушка ФСП ID и реестра ФСП",
    description="Демонстрационная реализация интерфейса ФСП ID (Keycloak) и реестра достижений.",
    version="1.0",
)

REGISTRY_AUDIENCE = "fsp-registry"
CODE_AUDIENCE = "fsp-authorization-code"


@lru_cache
def _key():
    private = load_or_create_rsa(get_settings().data_dir / "keys" / "mock_fsp.pem")
    public = private.public_key()
    kid = "mock-fsp-" + hashlib.sha256(
        public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()[:8]
    import json

    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return private, public, kid, jwk


def _issuer() -> str:
    return mock_public_base() + "/realms/fsp"


def _sign(claims: dict) -> str:
    private, _public, kid, _jwk = _key()
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


def _check_client(client_id: str, client_secret: str | None = None) -> None:
    settings = get_settings()
    if client_id != settings.fsp_client_id:
        raise HTTPException(400, "unknown client")
    if client_secret is not None and client_secret != settings.fsp_client_secret:
        raise HTTPException(401, "invalid client secret")


@mock_app.get("/realms/fsp/.well-known/openid-configuration", tags=["ФСП ID"])
def discovery():
    base = _issuer() + "/protocol/openid-connect"
    return {
        "issuer": _issuer(),
        "authorization_endpoint": base + "/auth",
        "token_endpoint": base + "/token",
        "jwks_uri": base + "/certs",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["openid", "profile"],
    }


@mock_app.get("/realms/fsp/protocol/openid-connect/certs", tags=["ФСП ID"])
def certs():
    return {"keys": [_key()[3]]}


@mock_app.get("/realms/fsp/protocol/openid-connect/auth", response_class=HTMLResponse, tags=["ФСП ID"])
def authorize(
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    response_type: str = "code",
):
    _check_client(client_id)
    if response_type != "code" or code_challenge_method != "S256":
        raise HTTPException(400, "unsupported response type")
    # точное совпадение, как у зарегистрированного клиента Keycloak: проверка по префиксу
    # пропустила бы http://localhost:8000.evil.example/…
    if redirect_uri != get_settings().public_base_url.rstrip("/") + "/api/v1/fsp/link/callback":
        raise HTTPException(400, "redirect_uri not allowed")
    hidden = "".join(
        "<input type='hidden' name='%s' value='%s'>" % (k, html.escape(v))
        for k, v in {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
        }.items()
    )
    action = mock_public_base() + "/realms/fsp/login-actions/authenticate"
    rows = []
    for p in participants().values():
        rows.append(
            "<form method='post' action='%s' style='margin:8px 0'>%s"
            "<input type='hidden' name='fsp_id' value='%s'>"
            "<button style='width:100%%;padding:10px;text-align:left;cursor:pointer'>"
            "<b>%s</b> · %s · %s · достижений: %d</button></form>"
            % (action, hidden, html.escape(p["fsp_id"]), html.escape(p["name"]), html.escape(p["fsp_id"]),
               html.escape(p.get("region") or ""), len(p.get("achievements", [])))
        )
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>ФСП ID — вход</title>"
        "<body style='font-family:sans-serif;max-width:640px;margin:40px auto;color:#1b2a4a'>"
        "<h2>ФСП ID</h2><p style='color:#a33'>Демонстрационная заглушка: выберите участника, под которым войти.</p>"
        + "".join(rows)
        + "</body>"
    )


@mock_app.post("/realms/fsp/login-actions/authenticate", tags=["ФСП ID"])
def authenticate(
    fsp_id: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    nonce: str = Form(...),
    code_challenge: str = Form(...),
):
    _check_client(client_id)
    if fsp_id not in participants():
        raise HTTPException(404, "participant not found")
    # Код авторизации — подписанный токен, а не запись в памяти: при
    # нескольких процессах uvicorn обмен кода может прийти в другой процесс.
    now = int(time.time())
    code = _sign({"iss": _issuer(), "aud": CODE_AUDIENCE, "sub": fsp_id, "client_id": client_id,
                  "redirect_uri": redirect_uri, "nonce": nonce, "challenge": code_challenge,
                  "iat": now, "exp": now + 120, "jti": secrets.token_urlsafe(8)})
    return RedirectResponse(redirect_uri + "?" + urlencode({"code": code, "state": state}), status_code=303)


@mock_app.post("/realms/fsp/protocol/openid-connect/token", tags=["ФСП ID"])
def token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
):
    _check_client(client_id, client_secret)
    now = int(time.time())
    if grant_type == "client_credentials":
        access = _sign(
            {"iss": _issuer(), "sub": "service-account-" + client_id, "aud": REGISTRY_AUDIENCE, "azp": client_id,
             "iat": now, "exp": now + 300, "jti": str(uuid.uuid4()), "realm_access": {"roles": ["registry-reader"]}}
        )
        return {"access_token": access, "token_type": "Bearer", "expires_in": 300}
    if grant_type != "authorization_code" or not code:
        raise HTTPException(400, "unsupported grant")
    try:
        entry = jwt.decode(code, _key()[1], algorithms=["RS256"], audience=CODE_AUDIENCE, issuer=_issuer())
    except jwt.PyJWTError as exc:
        raise HTTPException(400, "invalid code") from exc
    entry["fsp_id"] = entry["sub"]
    if entry["client_id"] != client_id or entry["redirect_uri"] != redirect_uri:
        raise HTTPException(400, "client or redirect mismatch")
    expected = base64.urlsafe_b64encode(hashlib.sha256((code_verifier or "").encode()).digest()).decode().rstrip("=")
    if expected != entry["challenge"]:
        raise HTTPException(400, "PKCE verification failed")
    person = participants()[entry["fsp_id"]]
    claims = {"iss": _issuer(), "sub": person["fsp_id"], "aud": client_id, "azp": client_id, "iat": now, "exp": now + 300}
    # ФСП ID сегодня по сути почта и пароль: почта приходит в id_token, как в Keycloak
    id_token = _sign(claims | {"nonce": entry["nonce"], "name": person["name"], "region": person.get("region"),
                               "preferred_username": person["fsp_id"], "email": person.get("email"),
                               "email_verified": bool(person.get("email"))})
    access = _sign(claims | {"typ": "Bearer", "jti": str(uuid.uuid4())})
    return {"access_token": access, "id_token": id_token, "token_type": "Bearer", "expires_in": 300}


def _require_service(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        jwt.decode(authorization[7:], _key()[1], algorithms=["RS256"], audience=REGISTRY_AUDIENCE, issuer=_issuer())
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid token") from exc


@mock_app.get("/api/participants/{fsp_id}", tags=["Реестр ФСП"])
def participant(fsp_id: str, authorization: str | None = Header(None)):
    _require_service(authorization)
    person = participants().get(fsp_id)
    if person is None:
        raise HTTPException(404, "participant not found")
    return {"fsp_id": person["fsp_id"], "name": person["name"], "region": person.get("region"),
            "email": person.get("email"), "sport_rank": person.get("sport_rank")}


@mock_app.get("/api/participants/{fsp_id}/achievements", tags=["Реестр ФСП"])
def achievements(fsp_id: str, authorization: str | None = Header(None)):
    _require_service(authorization)
    person = participants().get(fsp_id)
    if person is None:
        raise HTTPException(404, "participant not found")
    return {"fsp_id": fsp_id, "items": person.get("achievements", [])}
