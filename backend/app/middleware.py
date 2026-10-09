"""
Ограничение размера тела запроса.

Без него сервер читает тело любого размера целиком: длинный «пароль» или
многомегабайтный JSON занимают память и процессор. Загрузка резюме
получает свой предел (max_resume_mb), остальные запросы — max_body_kb.
Проверяется и заявленная длина (Content-Length), и фактически
прочитанные байты (на случай chunked-передачи).
"""

import json

from app.config import get_settings

RESUME_PATH_SUFFIX = "/profile/resume"


def _too_large(limit_bytes: int) -> tuple[dict, bytes]:
    body = json.dumps(
        {"error": {"code": "payload_too_large", "message": "Слишком большой запрос",
                   "details": {"limit_bytes": limit_bytes}}},
        ensure_ascii=False,
    ).encode("utf-8")
    start = {"type": "http.response.start", "status": 413,
             "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())]}
    return start, body


class BodySizeLimit:
    def __init__(self, app):
        self.app = app

    def _limit(self, path: str) -> int:
        settings = get_settings()
        if path.endswith(RESUME_PATH_SUFFIX):
            return settings.max_resume_mb * 1024 * 1024 + 64 * 1024  # запас на заголовки multipart
        return settings.max_body_kb * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self._limit(scope.get("path", ""))
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            start, body = _too_large(limit)
            await send(start)
            await send({"type": "http.response.body", "body": body})
            return

        received = 0
        rejected = False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    # приложение получит обрыв тела; ответ 413 отправим сами
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def guarded_send(message):
            nonlocal started
            if rejected and not started:
                start, body = _too_large(limit)
                started = True
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
