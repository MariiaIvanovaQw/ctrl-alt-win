"""
Слой хранения: движок SQLAlchemy, сессия и общие типы колонок.

Модели используют переносимые типы (Uuid, JSON, UTCDateTime), поэтому
одна и та же схема работает в SQLite для локального запуска и в
PostgreSQL в контейнере.
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator, Uuid, create_engine, event
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict] = {dict: JSON, list: JSON, uuid.UUID: Uuid}


class UTCDateTime(TypeDecorator):
    """
    Время всегда в UTC и всегда с часовым поясом.

    SQLite не хранит смещение, поэтому значение записывается как наивное
    UTC и при чтении снова получает tzinfo=UTC. Так сравнения времени
    одинаково работают в SQLite и PostgreSQL.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("ожидается время с часовым поясом")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_engine():
    url = get_settings().sqlalchemy_url
    # JSON в UTF-8, а не \uXXXX: кириллица в заданиях и результатах занимает втрое меньше места
    kwargs = {"pool_pre_ping": True, "json_serializer": lambda obj: json.dumps(obj, ensure_ascii=False)}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_schema() -> None:
    # Импорт моделей регистрирует таблицы в метаданных.
    import app.models  # noqa: F401

    # Несколько процессов uvicorn стартуют одновременно: кто-то может создать
    # таблицу между проверкой и CREATE другого — тогда повторяем.
    for attempt in range(3):
        try:
            Base.metadata.create_all(engine)
            upgrade_schema()
            return
        except DatabaseError:
            if attempt == 2:
                raise
            time.sleep(0.5)


def upgrade_schema() -> None:
    """
    Дополняет существующую базу новыми колонками и индексами.

    create_all не меняет уже созданные таблицы, а миграций (Alembic) в MVP
    нет. Новые колонки моделей поэтому всегда допускают NULL или имеют
    значение по умолчанию на стороне БД: их можно добавить через
    ALTER TABLE ADD COLUMN без пересоздания базы. Индекс, который не удалось
    создать (например, уникальный при уже имеющихся дублях), пропускается
    с предупреждением — данные не теряются.
    """
    import logging

    from sqlalchemy import inspect

    log = logging.getLogger("app.db")
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = "ALTER TABLE %s ADD COLUMN %s %s" % (
                table.name, column.name, column.type.compile(dialect=engine.dialect))
            if column.server_default is not None:
                ddl += " DEFAULT %s" % column.server_default.arg.text
            with engine.begin() as conn:
                conn.exec_driver_sql(ddl)
            log.info("схема: добавлена колонка %s.%s", table.name, column.name)
        for index in table.indexes:
            try:
                index.create(engine, checkfirst=True)
            except DatabaseError as exc:
                log.warning("схема: индекс %s не создан (%s) — пересоздайте демо-базу", index.name, exc.orig)
