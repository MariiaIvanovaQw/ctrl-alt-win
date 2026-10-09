"""
Настройки приложения.

Все значения читаются из переменных окружения с префиксом APP_ (или из
файла .env в каталоге backend). Значения по умолчанию рассчитаны на
локальный запуск без внешних сервисов: SQLite, встроенный провайдер
идентичности и встроенная заглушка ФСП ID.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="APP_", extra="ignore")

    # Безопасно по умолчанию: prod. Удобства локальной разработки (заглушка
    # ФСП ID без настройки) включает APP_ENV=dev, служебные методы для жюри —
    # отдельный флаг APP_DEMO_MODE.
    env: str = "prod"  # dev | prod
    # Демо-стенд для жюри: экспресс-тест и сброс попыток, ссылки из писем в
    # ответах API (подтверждение почты на демонстрации не обязательно), список
    # демо-учёток без модератора. Не включать на данных реальных людей.
    demo_mode: bool = False
    public_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    data_dir: Path = BASE_DIR / "data"
    database_url: str = ""  # по умолчанию sqlite в data_dir
    bank_dir: Path = REPO_DIR / "it-assessment-bank"

    # ---- аутентификация
    # local    — встроенный провайдер: регистрация, подтверждение почты и
    #            выпуск токенов в формате Keycloak (realm_access.roles);
    # keycloak — токены выпускает внешний Keycloak, API их только проверяет.
    auth_mode: str = "local"
    local_issuer_path: str = "/idp/realms/platform"
    jwt_audience: str = "talent-api"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    keycloak_issuer: str = ""  # например http://localhost:8080/realms/platform
    keycloak_jwks_url: str = ""  # по умолчанию {issuer}/protocol/openid-connect/certs
    keycloak_audience: str = "talent-api"

    # ---- почта
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    mail_from: str = "noreply@talent.local"
    email_verification_ttl_hours: int = 24
    require_email_verification: bool = True
    # Учётные записи — только на почте в российских доменах (данные граждан РФ
    # хранятся и обрабатываются в РФ, 152-ФЗ, ст. 18 ч. 5). Список доменов
    # верхнего уровня; при необходимости добавляется «рф» (xn--p1ai) и «su».
    email_allowed_tlds: list[str] = ["ru"]

    # ---- ФСП ID
    # inprocess — встроенная заглушка ФСП обслуживается этим же приложением
    #             (/mock-fsp), серверные запросы к ней идут без сети;
    # oidc      — внешний провайдер ФСП ID на Keycloak и реестр достижений.
    fsp_mode: str = "inprocess"
    fsp_issuer: str = ""  # для oidc: адрес realm ФСП ID в Keycloak
    fsp_api_url: str = ""  # для oidc: базовый адрес реестра достижений
    fsp_client_id: str = "talent-platform"
    fsp_client_secret: str = "dev-fsp-secret"
    # Заглушка ФСП ID пускает под любым участником реестра без пароля, поэтому
    # работает только в демо-режиме или при APP_ENV=dev (см. mock_fsp_allowed).
    mock_fsp_enabled: bool = True

    # ---- тестирование: правила платформы (app/services/assessment.py)
    attempt_time_limit_minutes: int = 60
    grade_change_cooldown_days: int = 90
    same_level_retry_days: int = 30
    # после неудачной попытки уровень ниже заявленного не рекомендуется, а
    # подтверждается только тестом этого уровня (закрывает «добор» угадыванием)
    recommendation_clean_days: int = 180
    # результат выше заявленного: столько дней можно пройти тест этого уровня без ожидания
    promotion_offer_days: int = 30
    seed_candidates: int = 5  # сколько сидов перебирать для минимального пересечения

    # ---- регулярные задания
    task_assign_interval_days: int = 14
    task_due_days: int = 7

    # ---- приглашения
    invitation_ttl_days: int = 14

    # ---- несовершеннолетние кандидаты (app/services/minors.py)
    min_candidate_age: int = 14  # младше — профиль не принимается
    guardian_link_days: int = 14  # срок ссылки для законного представителя
    invitations_per_company_per_day: int = 50

    # ---- защита от недобросовестных работодателей (app/services/trust.py)
    trust_window_days: int = 30
    trust_review_complaints: int = 3  # жалоб за окно, после которых компания уходит на проверку
    trust_review_share: float = 0.2  # …если это не меньше такой доли ответов кандидатов
    salary_max_ratio: float = 3.0  # верхняя граница вилки больше нижней во столько раз — предупреждение
    salary_market_ratio: float = 2.0  # нижняя граница выше рынка категории во столько раз — предупреждение

    # ---- вебхуки для ATS (app/services/webhooks.py)
    webhook_dispatch_interval_seconds: int = 5  # 0 — фоновый диспетчер выключен
    webhook_max_attempts: int = 6
    # адреса во внутренней сети (localhost, 10.0.0.0/8…) — только явной настройкой,
    # например для локального приёмника вебхуков при разработке
    webhook_allow_private_hosts: bool = False

    # ---- вход и восстановление доступа
    password_reset_ttl_minutes: int = 60
    login_failures_per_account_ip: int = 10  # неудачных входов на пару «почта + IP» за 15 минут
    login_failures_per_ip: int = 50  # неудачных входов с одного IP за 15 минут (перебор по многим адресам)

    # ---- хранение данных
    outbox_retention_days: int = 30  # копии отправленных писем в базе платформы
    min_work_age: int = 15  # приглашения и отклики — с 15 лет (лёгкий труд, ст. 63 ТК РФ)

    # ---- прочее
    max_resume_mb: int = 5
    max_body_kb: int = 1024  # предел тела запроса, кроме загрузки резюме
    pdf_font_path: str = ""

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return "sqlite:///" + (self.data_dir / "app.db").as_posix()

    @property
    def local_issuer(self) -> str:
        return self.public_base_url.rstrip("/") + self.local_issuer_path

    @property
    def bank_json(self) -> Path:
        return self.bank_dir / "dist" / "bank.json"

    @property
    def bank_tools(self) -> Path:
        return self.bank_dir / "tools"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def mock_fsp_allowed(self) -> bool:
        """Заглушка ФСП ID — только для демонстрации и разработки, не в эксплуатации."""
        return self.mock_fsp_enabled and (self.demo_mode or self.is_dev)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
