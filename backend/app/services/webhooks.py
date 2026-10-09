"""
Вебхуки для ATS работодателя.

Компания подписывает адрес своей ATS на события платформы, например
«кандидат принял приглашение». Когда событие происходит, ATS сама
получает данные кандидата и может завести карточку без ручного переноса.

Устройство:

* **Transactional outbox.** Событие пишется в `webhook_deliveries` в той
  же транзакции, что и изменение статуса. Запрос пользователя не ждёт
  сеть, и событие не теряется при сбое отправки.
* **Фоновый диспетчер** раз в несколько секунд отправляет готовые
  доставки. Доставку сначала атомарно «захватывают» (pending → sending),
  поэтому при нескольких процессах uvicorn событие не уходит дважды, а
  зависшая в sending доставка через 5 минут снова становится готовой.
  При ошибке он повторяет их с паузой 1, 2, 4… минуты и после
  `webhook_max_attempts` попыток помечает доставку failed. Повторить её
  можно вручную.
* **Подпись.** Заголовок `X-Talent-Signature: sha256=<HMAC-SHA256(secret, "<timestamp>.<тело>")>`
  и `X-Talent-Timestamp`. ATS проверяет подпись и отбрасывает старые
  запросы, чтобы их нельзя было переиграть.
* **Защита от SSRF.** Принимаются только https-адреса, все IP которых
  публичные (`is_global`: не частные сети, не localhost, не link-local
  169.254.0.0/16 с метаданными облака, не 100.64.0.0/10). Перед каждой
  отправкой имя резолвится заново, и запрос идёт на проверенный IP с
  исходным именем в Host и SNI: адрес нельзя подменить между проверкой и
  соединением (DNS rebinding). Редиректы не выполняются. Внутренние адреса
  разрешает только явная настройка APP_WEBHOOK_ALLOW_PRIVATE_HOSTS для
  локальной разработки.

Данные кандидата с контактами уходят только в событиях, после которых
работодатель и так видит контакты: принятое приглашение или отклик.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.errors import AppError
from app.models import WebhookDelivery, WebhookEndpoint

log = logging.getLogger("app.webhooks")

EVENTS = {
    "invitation.created": "Компания отправила приглашение (в том числе из интерфейса платформы)",
    "invitation.viewed": "Кандидат открыл приглашение",
    "invitation.accepted": "Кандидат принял приглашение (с данными кандидата)",
    "invitation.declined": "Кандидат отклонил приглашение (с причиной)",
    "invitation.expired": "Приглашение истекло без ответа",
    "invitation.withdrawn": "Компания отозвала приглашение",
    "application.created": "Новый отклик на вакансию (с данными кандидата)",
    "application.withdrawn": "Кандидат отозвал отклик",
    "application.invited": "Компания пригласила откликнувшегося на следующий этап",
    "application.rejected": "Компания отказала по отклику",
    "task.submitted": "Кандидат отправил решение регулярного задания",
}
PING = "ping"


# ------------------------------------------------------------------ адрес


def allow_private_hosts() -> bool:
    return get_settings().webhook_allow_private_hosts


@dataclass
class Target:
    """Куда реально отправлять: адрес с проверенным IP, заголовок Host и имя для TLS (SNI)."""

    url: str
    headers: dict = field(default_factory=dict)
    extensions: dict = field(default_factory=dict)


def _public_ip(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 — тот же localhost
    if not ip.is_global:
        raise AppError("Адрес указывает во внутреннюю сеть", code="invalid_webhook_url")
    return ip


def resolve_target(url: str, allow_private: bool | None = None) -> Target:
    """
    Проверяет адрес и закрепляет IP: все адреса имени должны быть
    публичными, запрос пойдёт на первый из них с исходным именем в Host и
    SNI (сертификат проверяется по имени, а не по IP).
    """
    allow_private = allow_private_hosts() if allow_private is None else allow_private
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise AppError("Нужен адрес вида https://ats.example.com/hooks/talent", code="invalid_webhook_url")
    if allow_private:
        return Target(url)
    if parsed.scheme != "https":
        raise AppError("Разрешены только адреса https", code="invalid_webhook_url")
    port = parsed.port or 443
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)]
    except (socket.gaierror, UnicodeError) as exc:
        raise AppError("Не удалось определить адрес сервера", code="invalid_webhook_url") from exc
    if not addresses:
        raise AppError("Не удалось определить адрес сервера", code="invalid_webhook_url")
    ips = [_public_ip(a) for a in addresses]
    pinned = ips[0]
    host = "[%s]" % pinned if pinned.version == 6 else str(pinned)
    netloc = host if parsed.port is None else "%s:%d" % (host, port)
    host_header = parsed.hostname if parsed.port is None else "%s:%d" % (parsed.hostname, port)
    return Target(parsed._replace(netloc=netloc).geturl(), {"Host": host_header}, {"sni_hostname": parsed.hostname})


def validate_url(url: str, allow_private: bool | None = None) -> str:
    resolve_target(url, allow_private)
    return url


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return "sha256=" + mac


# ------------------------------------------------------------------ события


def emit(db: Session, company_id: uuid.UUID, event: str, data: dict) -> int:
    """Записывает доставки события для подписанных адресов компании (в текущей транзакции)."""
    endpoints = db.scalars(
        select(WebhookEndpoint).where(WebhookEndpoint.company_id == company_id, WebhookEndpoint.active.is_(True))
    ).all()
    count = 0
    for endpoint in endpoints:
        if event != PING and event not in (endpoint.events or []):
            continue
        delivery_id = uuid.uuid4()
        payload = {
            "id": str(delivery_id),
            "event": event,
            "created_at": utcnow().isoformat(),
            "company_id": str(company_id),
            "data": data,
        }
        db.add(WebhookDelivery(id=delivery_id, endpoint_id=endpoint.id, event=event, payload=payload))
        count += 1
    return count


# ------------------------------------------------------------------ доставка


def _client() -> httpx.Client:
    return httpx.Client(timeout=5, follow_redirects=False)


def deliver(db: Session, delivery: WebhookDelivery, client: httpx.Client) -> bool:
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    settings = get_settings()
    body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "FSP-Talent-Webhooks/1.0",
        "X-Talent-Event": delivery.event,
        "X-Talent-Delivery": str(delivery.id),
        "X-Talent-Timestamp": timestamp,
        "X-Talent-Signature": sign(endpoint.secret, timestamp, body),
    }
    delivery.attempts += 1
    now = utcnow()
    try:
        # имя резолвится заново и запрос идёт на проверенный IP: адрес мог начать
        # указывать во внутреннюю сеть после создания подписки (DNS rebinding)
        target = resolve_target(endpoint.url)
        response = client.post(target.url, content=body, headers={**headers, **target.headers}, extensions=target.extensions)
        delivery.response_code = response.status_code
        ok = 200 <= response.status_code < 300
        error = None if ok else "HTTP %d" % response.status_code
    except (httpx.HTTPError, AppError) as exc:
        ok, error = False, str(getattr(exc, "message", exc))[:500]
    if ok:
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.last_error = None
        endpoint.last_success_at = now
        endpoint.last_error = None
    else:
        delivery.last_error = error
        endpoint.last_error = error
        if delivery.attempts >= settings.webhook_max_attempts:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = now + timedelta(minutes=2 ** (delivery.attempts - 1))
    return ok


DUE = ("pending", "sending")


def _claim(db: Session, delivery: WebhookDelivery) -> bool:
    """Атомарно забирает доставку себе; False — её уже взял другой процесс."""
    now = utcnow()
    result = db.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.id == delivery.id, WebhookDelivery.status.in_(DUE), WebhookDelivery.next_attempt_at <= now)
        .values(status="sending", next_attempt_at=now + timedelta(minutes=5))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        return False
    db.refresh(delivery)
    return True


def dispatch_due(db: Session, client: httpx.Client | None = None, limit: int = 50) -> int:
    """Отправляет доставки, которым подошёл срок. Возвращает число отправленных."""
    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.status.in_(DUE), WebhookDelivery.next_attempt_at <= utcnow())
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
    ).all()
    if not rows:
        return 0
    own = client is None
    client = client or _client()
    sent = 0
    try:
        for delivery in rows:
            if not _claim(db, delivery):
                continue
            deliver(db, delivery, client)
            db.commit()
            sent += 1
    finally:
        if own:
            client.close()
    return sent


def retry(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    delivery.status = "pending"
    delivery.next_attempt_at = utcnow()
    delivery.attempts = 0
    db.commit()
    return delivery


# ------------------------------------------------------------------ фоновый диспетчер


class Dispatcher:
    """Поток, который раз в interval секунд отправляет готовые доставки."""

    def __init__(self, interval: int):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="webhook-dispatcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval + 5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with SessionLocal() as db:
                    dispatch_due(db)
            except Exception:
                log.exception("ошибка отправки вебхуков")
