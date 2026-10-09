"""
Хеширование паролей: scrypt с индивидуальной солью.

scrypt входит в стандартную библиотеку (hashlib) и относится к функциям
с настраиваемой стоимостью по памяти и времени, поэтому перебор хешей
дорог. Параметры хранятся в самой строке хеша: их можно усилить позже,
а старые хеши останутся проверяемыми.
"""

import base64
import hashlib
import hmac
import re
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, _b64(salt), _b64(digest))


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # выравниваем время ответа для несуществующих пользователей
        hashlib.scrypt(b"dummy", salt=b"0" * 16, n=_N, r=_R, p=_P, dklen=_DKLEN)
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def email_domain_allowed(email: str) -> bool:
    """Почта в разрешённом домене верхнего уровня (по умолчанию только .ru)."""
    from app.config import get_settings

    domain = email.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    tld = domain.rsplit(".", 1)[-1]
    return tld in {t.lower().lstrip(".") for t in get_settings().email_allowed_tlds}


def allowed_tlds_text() -> str:
    from app.config import get_settings

    return ", ".join("." + t.lstrip(".") for t in get_settings().email_allowed_tlds)


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("не короче 8 символов")
    if not re.search(r"[A-Za-zА-Яа-яЁё]", password):
        problems.append("хотя бы одна буква")
    if not re.search(r"\d", password):
        problems.append("хотя бы одна цифра")
    return problems
