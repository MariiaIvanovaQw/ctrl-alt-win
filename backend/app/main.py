"""
Платформа подбора ИТ-специалистов с верифицированным профилем ФСП — API.

Модульный монолит: каждый модуль (идентичность, кандидаты, тестирование,
подбор, взаимодействие, ФСП, задания) имеет свои модели, сервисы и
маршруты и общается с другими через сервисный слой.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import (
    admin,
    auth,
    candidate_assessment,
    candidate_interactions,
    candidate_profile,
    employer,
    employer_interactions,
    fsp,
    guardian,
    integrations,
    public,
    system,
)
from app.config import get_settings
from app.db import create_schema
from app.errors import ERROR_RESPONSES, install_error_handlers
from app.middleware import BodySizeLimit
from app.services import maintenance
from app.services.bank import bank
from app.services.webhooks import Dispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # запросы к встроенной заглушке ФСП не засоряют журнал

TAGS = [
    {"name": "Аутентификация", "description": "Регистрация по почте с подтверждением, вход, токены (формат Keycloak)."},
    {"name": "Кандидат: профиль", "description": "Профиль и резюме, опрос, приватность, согласия, выгрузка и удаление данных."},
    {"name": "Кандидат: тестирование", "description": "Персональный тест, грейд, рекомендации и правила пересдачи."},
    {"name": "Кандидат: приглашения и отклики", "description": "Входящие приглашения, вакансии и отклики, регулярные задания."},
    {"name": "Кандидат: ФСП ID", "description": "Привязка ФСП ID (OIDC) и достижения из реестра ФСП."},
    {"name": "Работодатель: подбор", "description": "Компания, потребности, подборки с обоснованием, категории и поиск."},
    {"name": "Работодатель: выход на контакт", "description": "Приглашения со статусами, отклики, регулярные задания."},
    {"name": "Работодатель: интеграции (ATS)", "description": "Вебхуки о событиях с подписью HMAC и выгрузка кандидата в JSON Resume."},
    {"name": "Модерация", "description": "Компании на проверке после жалоб кандидатов (роль admin)."},
    {"name": "Справочники и вакансии", "description": "Справочники, ролевые профили и механика теста, вакансии."},
    {"name": "Служебное", "description": "JWKS локального провайдера, инструменты разработки."},
]


log = logging.getLogger("app")


def _warn_about_mode() -> None:
    settings = get_settings()
    if settings.demo_mode:
        log.warning(
            "ДЕМО-РЕЖИМ (APP_DEMO_MODE=true): открыты служебные методы /api/v1/dev/* (экспресс-тест, сброс попыток), "
            "ссылки из писем возвращаются в ответах API. Не используйте с данными реальных людей."
        )
    if settings.mock_fsp_allowed:
        log.warning("Заглушка ФСП ID включена (/mock-fsp): вход под любым участником реестра без пароля — только для демо.")
    elif settings.fsp_mode == "inprocess":
        log.warning("ФСП ID не настроен: заглушка доступна только в демо-режиме или при APP_ENV=dev (APP_FSP_MODE=oidc для боевого ФСП ID).")
    if settings.webhook_allow_private_hosts:
        log.warning("Вебхуки разрешены на адреса внутренней сети (APP_WEBHOOK_ALLOW_PRIVATE_HOSTS=true) — только для разработки.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_schema()
    bank()  # загрузка банка заданий при старте, а не на первом запросе
    _warn_about_mode()
    maintenance.run_once()
    housekeeper = maintenance.Housekeeper()
    housekeeper.start()
    interval = get_settings().webhook_dispatch_interval_seconds
    dispatcher = Dispatcher(interval) if interval > 0 else None
    if dispatcher:
        dispatcher.start()
    yield
    housekeeper.stop()
    if dispatcher:
        dispatcher.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Платформа подбора ИТ-специалистов ФСП — API",
        version="1.0.0",
        description=(
            "Обратная механика найма: кандидат проходит опрос и тест, получает категорию "
            "(специализация + грейд), работодатель находит категорию и приглашает конкретного "
            "кандидата с вилкой зарплаты. Ошибки возвращаются в формате "
            '`{"error": {"code", "message", "details"}}`.'
        ),
        openapi_tags=TAGS,
        responses={k: v for k, v in ERROR_RESPONSES.items() if k in (401, 422)},
        lifespan=lifespan,
    )
    # Последний добавленный middleware — внешний: CORS снаружи, чтобы ответ 413
    # тоже нёс заголовки CORS и браузер показал сообщение, а не ошибку CORS.
    app.add_middleware(BodySizeLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    for module in (
        auth,
        candidate_profile,
        candidate_assessment,
        candidate_interactions,
        fsp,
        guardian,
        employer,
        employer_interactions,
        integrations,
        admin,
        public,
        system,
    ):
        app.include_router(module.router)
    if settings.mock_fsp_allowed:
        from app.mock_fsp.app import mock_app

        app.mount("/mock-fsp", mock_app)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    return app


app = create_app()
