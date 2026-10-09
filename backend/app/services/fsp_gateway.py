"""
Клиент ФСП ID (OpenID Connect поверх Keycloak) и реестра достижений.

Привязка профиля — стандартный поток Authorization Code с PKCE:
1. API создаёт state, nonce и code_verifier и отдаёт адрес входа в ФСП ID;
2. участник входит в ФСП ID, браузер возвращается на /api/v1/fsp/link/callback;
3. API обменивает код на токены, проверяет подпись id_token по JWKS,
   iss, aud и nonce, берёт sub как ФСП ID;
4. по ФСП ID с сервисным токеном (client_credentials) запрашиваются
   профиль и достижения из реестра.

Режим inprocess обслуживает те же запросы встроенной заглушкой без сети
(клиент — TestClient поверх ASGI-приложения заглушки); режим oidc ходит
по HTTP к настоящему провайдеру. Код потока в обоих режимах один.
"""

import base64
import hashlib
import secrets
import time
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

from app.config import get_settings
from app.errors import AppError


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def mock_public_base() -> str:
    return get_settings().public_base_url.rstrip("/") + "/mock-fsp"


class FspGateway:
    def __init__(self, http: httpx.Client, issuer: str, api_base: str, public_prefix: str | None = None):
        self.http = http
        self.issuer = issuer.rstrip("/")
        self.api_base = api_base.rstrip("/")
        # для inprocess: абсолютные адреса заглушки превращаются в пути ASGI-приложения
        self.public_prefix = public_prefix
        self._discovery = None
        self._service_token: tuple[str, float] | None = None

    # -------------------------------------------------------------- транспорт

    def _url(self, url: str) -> str:
        if self.public_prefix and url.startswith(self.public_prefix):
            return url[len(self.public_prefix):] or "/"
        return url

    def _get(self, url: str, **kwargs) -> dict:
        try:
            response = self.http.get(self._url(url), **kwargs)
        except httpx.HTTPError as exc:
            raise AppError("Сервис ФСП недоступен", code="fsp_unavailable", status_code=502) from exc
        if response.status_code >= 400:
            raise AppError("Сервис ФСП вернул ошибку %d" % response.status_code, code="fsp_error", status_code=502)
        return response.json()

    def _post_form(self, url: str, data: dict) -> dict:
        try:
            response = self.http.post(self._url(url), data=data)
        except httpx.HTTPError as exc:
            raise AppError("Сервис ФСП недоступен", code="fsp_unavailable", status_code=502) from exc
        if response.status_code >= 400:
            raise AppError("ФСП ID отклонил запрос: %s" % response.text[:200], code="fsp_auth_failed", status_code=502)
        return response.json()

    # -------------------------------------------------------------- OIDC

    def discovery(self) -> dict:
        if self._discovery is None:
            self._discovery = self._get(self.issuer + "/.well-known/openid-configuration")
        return self._discovery

    def authorization_url(self, state: str, challenge: str, nonce: str, redirect_uri: str) -> str:
        settings = get_settings()
        params = {
            "client_id": settings.fsp_client_id,
            "response_type": "code",
            "scope": "openid profile",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return self.discovery()["authorization_endpoint"] + "?" + urlencode(params)

    def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> dict:
        settings = get_settings()
        return self._post_form(
            self.discovery()["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.fsp_client_id,
                "client_secret": settings.fsp_client_secret,
                "code_verifier": verifier,
            },
        )

    def verify_id_token(self, id_token: str, nonce: str) -> dict:
        settings = get_settings()
        jwks = self._get(self.discovery()["jwks_uri"])
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
            jwk = next(k for k in jwks["keys"] if k.get("kid") == kid)
            key = jwt.PyJWK(jwk).key
            claims = jwt.decode(
                id_token, key, algorithms=["RS256"], audience=settings.fsp_client_id, issuer=self.issuer
            )
        except (StopIteration, jwt.PyJWTError) as exc:
            raise AppError("Подпись ответа ФСП ID не прошла проверку", code="fsp_token_invalid", status_code=502) from exc
        if claims.get("nonce") != nonce:
            raise AppError("Ответ ФСП ID не соответствует запросу", code="fsp_nonce_mismatch", status_code=502)
        return claims

    def _service_bearer(self) -> str:
        settings = get_settings()
        if self._service_token and self._service_token[1] > time.time() + 30:
            return self._service_token[0]
        data = self._post_form(
            self.discovery()["token_endpoint"],
            {
                "grant_type": "client_credentials",
                "client_id": settings.fsp_client_id,
                "client_secret": settings.fsp_client_secret,
            },
        )
        self._service_token = (data["access_token"], time.time() + int(data.get("expires_in", 300)))
        return data["access_token"]

    # -------------------------------------------------------------- реестр

    def participant(self, fsp_id: str) -> dict:
        return self._get(
            "%s/participants/%s" % (self.api_base, fsp_id),
            headers={"Authorization": "Bearer " + self._service_bearer()},
        )

    def achievements(self, fsp_id: str) -> list[dict]:
        data = self._get(
            "%s/participants/%s/achievements" % (self.api_base, fsp_id),
            headers={"Authorization": "Bearer " + self._service_bearer()},
        )
        return data.get("items", [])


@lru_cache
def gateway() -> FspGateway:
    settings = get_settings()
    if settings.fsp_mode == "inprocess":
        if not settings.mock_fsp_allowed:
            # заглушка пускает под любым участником без пароля — в эксплуатации её нет
            raise AppError("Интеграция с ФСП ID не настроена", code="fsp_not_configured", status_code=503)
        from fastapi.testclient import TestClient

        from app.mock_fsp.app import mock_app

        base = mock_public_base()
        return FspGateway(
            TestClient(mock_app, base_url="http://mock-fsp.internal"),
            issuer=base + "/realms/fsp",
            api_base=base + "/api",
            public_prefix=base,
        )
    if not settings.fsp_issuer or not settings.fsp_api_url:
        raise AppError("Интеграция с ФСП не настроена", code="fsp_not_configured", status_code=503)
    return FspGateway(httpx.Client(timeout=10), issuer=settings.fsp_issuer, api_base=settings.fsp_api_url)
