"""
Простое ограничение частоты в памяти процесса.

Счётчики живут в памяти каждого процесса uvicorn: при N процессах
фактический предел до N раз выше. Для MVP этого достаточно; при
нескольких серверах счётчики переносятся в Redis без изменения интерфейса.

Вход ограничивается по неудачным попыткам, а не по всем:

* пара «почта + IP» — подбор пароля к одной учётной записи;
* один IP — перебор одного пароля по многим адресам.

Счётчика «только по почте» нет намеренно: иначе любой мог бы
заблокировать чужой вход десятью неверными паролями.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.errors import TooManyRequests


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, bucket: deque, now: float) -> None:
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()

    def check(self, key: str, message: str = "Слишком много попыток, повторите позже", limit: int | None = None) -> None:
        """Отказ, если предел уже исчерпан; попытка при этом не засчитывается."""
        limit = self.limit if limit is None else limit
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return
            self._trim(bucket, now)
            if len(bucket) >= limit:
                retry = int(self.window - (now - bucket[0])) + 1
                raise TooManyRequests(message, details={"retry_after_seconds": retry})

    def add(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def hit(self, key: str, message: str = "Слишком много попыток, повторите позже") -> None:
        """Проверка и учёт попытки одним вызовом."""
        self.check(key, message)
        self.add(key)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


login_limiter = SlidingWindowLimiter(limit=10, window_seconds=900)
register_limiter = SlidingWindowLimiter(limit=20, window_seconds=3600)
password_limiter = SlidingWindowLimiter(limit=5, window_seconds=3600)
