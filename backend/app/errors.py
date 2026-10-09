"""
Единый формат ошибок API.

Любая ошибка возвращается как
    {"error": {"code": "machine_code", "message": "Текст для человека", "details": {...}}}
Код — стабильная строка для клиента, сообщение — для показа пользователю.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class TooManyRequests(AppError):
    status_code = 429
    code = "too_many_requests"


def _payload(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_payload(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        fields = []
        for err in exc.errors():
            fields.append({"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": err.get("msg")})
        return JSONResponse(
            _payload("validation_error", "Данные запроса не прошли проверку", {"fields": fields}), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(_payload(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):  # pragma: no cover - страховка
        import logging

        logging.getLogger("app").exception("необработанная ошибка: %s", exc)
        return JSONResponse(_payload("internal_error", "Внутренняя ошибка сервера"), status_code=500)


class ErrorDetail(BaseModel):
    code: str = Field(description="Стабильный машинный код, например not_found, attempt_in_progress")
    message: str = Field(description="Текст для показа пользователю")
    details: dict = Field(default_factory=dict, description="Подробности: поля с ошибками, дата доступности и т. п.")


class ErrorOut(BaseModel):
    error: ErrorDetail


ERROR_DESCRIPTIONS = {
    400: "Некорректный запрос (код в error.code)",
    401: "Нет или недействителен токен доступа",
    403: "Недостаточно прав, другая роль, неподтверждённая почта или компания на проверке",
    404: "Объект не найден или принадлежит другому пользователю",
    409: "Конфликт с текущим состоянием (код и подробности в error.code и error.details)",
    413: "Слишком большой запрос",
    422: "Ошибка валидации полей (error.details.fields)",
    429: "Слишком много запросов (error.details.retry_after_seconds)",
    502: "Внешний сервис (ФСП ID) вернул ошибку",
    503: "Внешний сервис не настроен",
}

ERROR_RESPONSES = {
    code: {"model": ErrorOut, "description": text} for code, text in ERROR_DESCRIPTIONS.items()
}


def errors(*codes: int) -> dict:
    """Описание ответов с ошибками для OpenAPI: responses=errors(404, 409)."""
    return {code: ERROR_RESPONSES[code] for code in codes}
