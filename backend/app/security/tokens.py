"""
Токены доступа в формате Keycloak.

В локальном режиме API само выпускает JWT, подписанные RS256, с теми же
полями, что выдаёт Keycloak: iss, sub, aud, azp, typ, email, email_verified,
preferred_username и realm_access.roles. Открытый ключ публикуется как JWKS
по адресу …/protocol/openid-connect/certs. Поэтому переход на внешний
Keycloak (в том числе на ФСП ID) — это смена конфигурации, а не кода:
проверка токена одинакова в обоих режимах.
"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization

from app.config import get_settings
from app.db import utcnow
from app.errors import Unauthorized
from app.security.keyfile import load_or_create_rsa

ALGORITHM = "RS256"
CLIENT_ID = "talent-web"


@dataclass
class SigningKey:
    private_pem: bytes
    public_pem: bytes
    kid: str
    jwk: dict


def _load_or_create_key() -> SigningKey:
    settings = get_settings()
    private_key = load_or_create_rsa(settings.data_dir / "keys" / "jwt_signing.pem")
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    kid = hashlib.sha256(public_pem).hexdigest()[:16]
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": kid, "use": "sig", "alg": ALGORITHM})
    return SigningKey(private_pem, public_pem, kid, jwk)


@lru_cache
def signing_key() -> SigningKey:
    return _load_or_create_key()


def jwks() -> dict:
    return {"keys": [signing_key().jwk]}


def issue_access_token(user) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    claims = {
        "iss": settings.local_issuer,
        "sub": str(user.id),
        "aud": [settings.jwt_audience, "account"],
        "azp": CLIENT_ID,
        "typ": "Bearer",
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": str(uuid.uuid4()),
        "email": user.email,
        "email_verified": bool(user.email_verified),
        "preferred_username": user.email,
        "realm_access": {"roles": [user.role]},
        "scope": "openid profile email",
    }
    key = signing_key()
    token = jwt.encode(claims, key.private_pem, algorithm=ALGORITHM, headers={"kid": key.kid})
    return token, int(ttl.total_seconds())


def new_refresh_token() -> tuple[str, str]:
    """Непрозрачный refresh-токен и его хеш для хранения."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ проверка


@lru_cache
def _keycloak_jwks_client():
    settings = get_settings()
    url = settings.keycloak_jwks_url or settings.keycloak_issuer.rstrip("/") + "/protocol/openid-connect/certs"
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        if settings.auth_mode == "keycloak":
            key = _keycloak_jwks_client().get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=settings.keycloak_audience,
                issuer=settings.keycloak_issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        return jwt.decode(
            token,
            signing_key().public_pem,
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.local_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Срок действия токена истёк", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Недействительный токен доступа", code="invalid_token") from exc


def roles_from_claims(claims: dict) -> list[str]:
    """Роли из realm_access, как их кладёт Keycloak."""
    return list((claims.get("realm_access") or {}).get("roles") or [])
