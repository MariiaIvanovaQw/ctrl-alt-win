"""Устройство API: предел размера запроса, дополнение схемы базы, описание ответов в OpenAPI."""

import uuid

from sqlalchemy import select

from tests.conftest import employer_with_company, graded_candidate, public_id


def test_request_body_size_is_limited(client):
    r = client.post("/api/v1/auth/login", content=b"{" + b" " * (2 * 1024 * 1024) + b"}",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_schema_upgrade_warns_instead_of_failing_on_duplicates(client, db, caplog):
    """Старая база с дублями: уникальный индекс не создаётся, API всё равно стартует."""
    from sqlalchemy import delete, insert, inspect

    from app.db import engine, upgrade_schema
    from app.models import TaskAssignment

    emp = employer_with_company(client, "ООО Схема")
    task = client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Индексы", "body": "Когда составной индекс не поможет запросу с фильтром по второй колонке?",
        "kind": "approach", "specialization": "backend"}).json()
    cand = graded_candidate(client, "backend", "middle")
    assert client.post("/api/v1/employer/tasks/%s/assign" % task["id"], headers=emp.headers,
                       json={"candidate_id": public_id(client, cand)}).status_code == 201
    a = db.scalar(select(TaskAssignment).where(TaskAssignment.task_id == uuid.UUID(task["id"])))
    db.commit()  # в PostgreSQL открытая транзакция с чтением таблицы не дала бы удалить индекс
    duplicate = uuid.uuid4()
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX uq_task_assignments_task_candidate")
        conn.execute(insert(TaskAssignment.__table__).values(
            id=duplicate, task_id=a.task_id, candidate_user_id=a.candidate_user_id,
            status="assigned", assigned_at=a.assigned_at, due_at=a.due_at))

    def indexes():
        return {i["name"] for i in inspect(engine).get_indexes("task_assignments")}

    with caplog.at_level("WARNING", logger="app.db"):
        upgrade_schema()
    assert "uq_task_assignments_task_candidate" in caplog.text
    assert "uq_task_assignments_task_candidate" not in indexes()

    with engine.begin() as conn:
        conn.execute(delete(TaskAssignment.__table__).where(TaskAssignment.__table__.c.id == duplicate))
    upgrade_schema()
    assert "uq_task_assignments_task_candidate" in indexes()


def test_openapi_describes_responses_and_errors(client):
    spec = client.get("/openapi.json").json()
    untyped = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            responses = op["responses"]
            ok = [c for c in responses if c.startswith("2")]
            if ok == ["204"] or path.endswith(("/pdf", "/callback", "/verify-email")):
                continue
            content = responses[ok[0]].get("content", {}).get("application/json", {})
            if not content.get("schema"):
                untyped.append("%s %s" % (method.upper(), path))
    assert untyped == []
    errors_schema = spec["components"]["schemas"]["ErrorOut"]
    assert "error" in errors_schema["properties"]
