# Образ API. Собирается из корня репозитория (нужен соседний каталог
# it-assessment-bank с банком заданий):
#   docker build -f backend/Dockerfile -t fsp-talent-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Шрифт с кириллицей для PDF-профилей
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY it-assessment-bank /app/it-assessment-bank
COPY backend /app/backend

ENV APP_BANK_DIR=/app/it-assessment-bank \
    APP_DATA_DIR=/data

RUN useradd --system --uid 10001 app \
    && mkdir -p /data \
    && chown app /data
USER app

EXPOSE 8000
# Пустая база при первом запуске заполняется демо-данными; дальше данные сохраняются.
# Число процессов uvicorn берёт из WEB_CONCURRENCY.
CMD ["sh", "-c", "python -m scripts.seed_demo --if-empty && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
