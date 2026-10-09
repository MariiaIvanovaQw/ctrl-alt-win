# API платформы

FastAPI, SQLAlchemy, PostgreSQL или SQLite. Банк заданий и алгоритмы
оценки – в соседнем каталоге [`../it-assessment-bank`](../it-assessment-bank/README.md);
API использует его эталонную реализацию и собранный `dist/bank.json`.

## Запуск

Python 3.10+. Внешние сервисы не нужны: SQLite, встроенный провайдер
входа и имитация ФСП ID.

```bash
python -m venv .venv
.venv\Scripts\activate                # Linux, macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                # Linux, macOS: cp .env.example .env
python -m scripts.seed_demo --reset   # 240 кандидатов, 3 компании, 6 вакансий
uvicorn app.main:app --port 8000
```

Swagger UI – http://localhost:8000/docs, проверка – `/api/v1/health`,
имитация ФСП ID – `/mock-fsp/docs`. Учётные записи – в
`data/demo_accounts.json`: общий пароль у жюри (`jury1…jury5@demo-fsp.ru`),
работодателей (`hr1…hr3@demo-fsp.ru`) и кандидатов, у модератора – свой.
Демо-учётные записи нельзя удалить и сменить им пароль.

**Режимы.** Без `.env` API работает безопасно (`APP_ENV=prod`): нет
служебных методов `/api/v1/dev/*` и имитации ФСП ID. `.env` из примера
включает `APP_ENV=dev` и демо-режим `APP_DEMO_MODE=true`: экспресс-режим
теста, сброс попыток, ссылки из писем в ответах API. Не включайте его на
данных реальных людей.

В Windows запускайте один процесс: общий сокет нескольких процессов
uvicorn (`--workers 4`) изредка теряет соединение. В Docker API работает
в четырёх процессах.

Миграций нет: при старте API добавляет в существующую базу новые колонки
и индексы. Если демо-база устарела – `python -m scripts.seed_demo --reset`.

## Настройки

Переменные с префиксом `APP_` или файл `.env`; полный список с
пояснениями – [`app/config.py`](app/config.py), пример – [`.env.example`](.env.example).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `APP_ENV`, `APP_DEMO_MODE` | `prod`, `false` | разработка и демо-стенд |
| `APP_DATABASE_URL` | SQLite в `data/` | например `postgresql+psycopg://user:pass@host:5432/db` |
| `APP_DATA_DIR`, `APP_BANK_DIR` | `data/`, `../it-assessment-bank` | данные (база, ключи, резюме) и банк заданий |
| `APP_AUTH_MODE` | `local` | `keycloak` – проверять токены внешнего Keycloak (`APP_KEYCLOAK_ISSUER`, `…_JWKS_URL`, `…_AUDIENCE`) |
| `APP_FSP_MODE` | `inprocess` | `oidc` – настоящий ФСП ID (`APP_FSP_ISSUER`, `APP_FSP_API_URL`, `APP_FSP_CLIENT_ID`, `APP_FSP_CLIENT_SECRET`) |
| `APP_SMTP_HOST`, `APP_SMTP_PORT` | – | без SMTP письма не отправляются, копии хранятся в базе |
| `APP_GRADE_CHANGE_COOLDOWN_DAYS`, `APP_SAME_LEVEL_RETRY_DAYS`, `APP_RECOMMENDATION_CLEAN_DAYS` | 90, 30, 180 | правила пересдачи |
| `APP_WEBHOOK_DISPATCH_INTERVAL_SECONDS` | 5 | отправка вебхуков, 0 – выключить |

## Docker и Keycloak

Из корня репозитория: `docker compose up --build` – веб, API, PostgreSQL и
Mailpit. Пароли и адреса – в `.env` рядом с `docker-compose.yml`
(`POSTGRES_PASSWORD`, `APP_PUBLIC_BASE_URL`, `APP_CORS_ORIGINS`,
`VITE_API_BASE` и др.).

`APP_AUTH_MODE=keycloak docker compose --profile keycloak up --build`
добавляет Keycloak с realm `platform` из
[`deploy/keycloak/platform-realm.json`](deploy/keycloak/platform-realm.json):
роли `candidate`, `employer`, `admin`, клиент `talent-web` (Authorization
Code + PKCE). API в этом режиме только проверяет токены; встроенный
провайдер выпускает токены той же структуры.

## Скрипты и проверки

| Команда | Результат |
|---|---|
| `python -m scripts.seed_demo --reset` | демо-данные; кандидаты проходят тест через настоящие сервисы, сид воспроизводим |
| `python -m scripts.evaluate --runs 5` | валидация категоризации, подбора и правил пересдачи → `reports/evaluation_report.md` |
| `python -m scripts.item_analysis` | трудность и различающая сила заданий → `reports/item_analysis.md` |
| `python -m scripts.benchmark` | нагрузочная проверка запущенного сервера → `reports/benchmark.md` |
| `python -m scripts.export_openapi` | `../docs/openapi.json` |
| `python -m scripts.build_docs` | `../docs/documentation.pdf` из `documentation.md` |
| `python -m scripts.make_sample_resume` | вымышленное резюме `samples/resume-demo.pdf` для проверки распознавания |

```bash
pip install -r requirements-dev.txt
python -m pytest        # 138 тестов на временной SQLite
```

Линтер – `ruff check .` из корня репозитория (настройки в `ruff.toml`).

Тот же набор на PostgreSQL (база очищается перед прогоном):

```bash
docker run -d --name fsp-test-pg -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data postgres:16-alpine
TEST_DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:55432/test python -m pytest
```

## Структура

```
app/
  main.py, config.py, db.py, errors.py   сборка приложения, настройки, хранение, формат ошибок
  reference.py, schemas.py               справочники и общие схемы
  models/      таблицы модулей: identity, candidates, assessment, fsp, employers, interactions, tasks, integrations
  services/    бизнес-логика: assessment, matching, search, interactions, fsp, tasks, trust, webhooks…
  api/         HTTP-маршруты модулей
  security/    пароли (scrypt), токены (RS256, формат Keycloak), зависимости ролей
  mock_fsp/    имитация ФСП ID (OIDC) и реестра достижений
  data/        ролевые профили и демо-вакансии
scripts/       демо-данные, валидация, нагрузка, сборка документации
tests/         pytest по модулям
reports/       отчёты валидации, анализа заданий и нагрузки
samples/       вымышленное PDF-резюме
deploy/        realm для Keycloak
```
