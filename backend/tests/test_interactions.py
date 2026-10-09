"""Подборка, приглашения со статусами, раскрытие контактов, вакансии и отклики, задания."""

from sqlalchemy import select

from app.models import Company, EmployerTask, OutboxEmail, User
from tests.conftest import (
    create_need,
    employer_with_company,
    graded_candidate,
    last_mail,
    miss_first_lookup,
    public_id,
    register,
)


def _invite(client, emp, candidate_id, need_id=None, selection_id=None, **extra):
    body = {
        "candidate_id": candidate_id,
        "title": "Python-разработчик",
        "description": "Приглашаем в команду платёжного сервиса, работа удалённо",
        "salary_from": 230000,
        "salary_to": 290000,
        "contact_method": "hr@example.com",
    }
    if need_id:
        body["need_id"] = need_id
    if selection_id:
        body["selection_id"] = selection_id
    body.update(extra)
    return client.post("/api/v1/employer/invitations", headers=emp.headers, json=body)


def test_selection_explains_ranking_and_hides_contacts(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    need = create_need(client, emp)
    assert need["profile"]["top_competencies"], "из описания построен профиль компетенций"
    r = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={})
    assert r.status_code == 201
    sel = r.json()
    row = next(x for x in sel["results"] if x["candidate_id"] == public_id(client, cand))
    factors = row["match"]["factors"]
    assert {f["factor"] for f in factors} == {"competencies", "test", "stack", "fsp", "freshness"}
    assert abs(sum(f["contribution"] for f in factors) - row["match"]["base_score"]) < 0.2
    assert all(f["text"] for f in factors), "каждый фактор объяснён текстом"
    assert row["candidate"]["contacts"] is None
    assert "Петров" not in str(row["candidate"])  # без согласия на показ ФИО — только инициалы
    # карточка одного кандидата считает место по всей категории, как и подборка
    card = client.get("/api/v1/employer/candidates/%s" % row["candidate_id"], headers=emp.headers).json()
    assert card["test"]["percentile_in_category"] == row["candidate"]["test"]["percentile_in_category"]
    assert card["test"]["level_band_rate"] == row["candidate"]["test"]["level_band_rate"]


def test_refine_keeps_parent_selection(client):
    graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    need = create_need(client, emp)
    first = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={}).json()
    r = client.post("/api/v1/employer/selections/%s/refine" % first["id"], headers=emp.headers, json={"has_fsp": True})
    assert r.status_code == 201
    child = r.json()
    assert child["parent_id"] == first["id"]
    again = client.get("/api/v1/employer/selections/%s" % first["id"], headers=emp.headers).json()
    assert again["summary"]["total_matched"] == first["summary"]["total_matched"]


def test_invitation_lifecycle_reveals_contacts_after_accept(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    cid = public_id(client, cand)
    r = _invite(client, emp, cid)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert _invite(client, emp, cid).json()["error"]["code"] == "invitation_exists"
    card = client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).json()
    assert card["contacts"] is None

    inbox = client.get("/api/v1/candidate/invitations", headers=cand.headers).json()
    assert inbox[0]["salary_from"] == 230000 and inbox[0]["salary_to"] == 290000
    client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=cand.headers)
    r = client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=cand.headers, json={"message": "Готов обсудить"})
    assert [e["event"] for e in r.json()["timeline"]] == ["sent", "viewed", "accepted"]

    card = client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).json()
    assert card["contacts"]["phone"] == "+79000000001"
    pdf = client.get("/api/v1/employer/candidates/%s/pdf" % cid, headers=emp.headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_decline_with_reason(client):
    cand = graded_candidate(client, "qa", "junior", stack=["sql", "postman"])
    emp = employer_with_company(client)
    inv = _invite(client, emp, public_id(client, cand)).json()
    r = client.post("/api/v1/candidate/invitations/%s/decline" % inv["id"], headers=cand.headers, json={"reason": "salary", "comment": "Ниже ожиданий"})
    assert r.json()["status"] == "declined"
    stats = client.get("/api/v1/employer/invitations-stats", headers=emp.headers).json()
    assert stats["by_status"] == {"declined": 1}
    assert stats["decline_reasons"][0]["reason"] == "salary"


def test_invitation_requires_salary_range(client):
    cand = graded_candidate(client, "frontend", "junior", stack=["react"])
    emp = employer_with_company(client)
    r = _invite(client, emp, public_id(client, cand), salary_from=300000, salary_to=200000)
    assert r.status_code == 422
    body = {"candidate_id": public_id(client, cand), "title": "Без вилки", "description": "Описание предложения без зарплаты", "contact_method": "hr@x.ru"}
    assert client.post("/api/v1/employer/invitations", headers=emp.headers, json=body).status_code == 422


def test_unpublished_candidate_is_not_visible(client):
    cand = graded_candidate(client, "backend", "middle")
    cid = public_id(client, cand)
    client.post("/api/v1/candidate/consents", headers=cand.headers, json={"kind": "profile_publication", "granted": False})
    emp = employer_with_company(client)
    need = create_need(client, emp)
    sel = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={}).json()
    assert cid not in {x["candidate_id"] for x in sel["results"]}
    assert client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).status_code == 404


def test_application_reveals_contacts_to_that_company_only(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    other = employer_with_company(client, "ООО Другая")
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    assert need["id"] in {v["id"] for v in client.get("/api/v1/vacancies").json()["items"]}
    r = client.post("/api/v1/candidate/applications", headers=cand.headers, json={"need_id": need["id"], "cover_letter": "Интересно"})
    assert r.status_code == 201
    cid = public_id(client, cand)
    assert client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).json()["contacts"] is not None
    assert client.get("/api/v1/employer/candidates/%s" % cid, headers=other.headers).json()["contacts"] is None


def test_regular_task_assignment_and_review(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    r = client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Сколько запросов", "kind": "numeric", "specialization": "backend", "correct_number": 21,
        "body": "Код загружает 20 заказов и для каждого клиента отдельным запросом. Сколько всего запросов?"})
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]
    tasks = client.get("/api/v1/candidate/tasks", headers=cand.headers).json()
    mine = next(t for t in tasks if t["task"]["title"] == "Сколько запросов")
    r = client.post("/api/v1/candidate/tasks/%s/submit" % mine["id"], headers=cand.headers, json={"number": 21})
    assert r.status_code == 200, r.text
    assert r.json()["auto_correct"] is True
    again = client.post("/api/v1/candidate/tasks/%s/submit" % mine["id"], headers=cand.headers, json={"number": 20})
    assert again.json()["error"]["code"] == "task_closed"
    subs = client.get("/api/v1/employer/tasks/%s/submissions" % task_id, headers=emp.headers).json()["submissions"]
    assert subs[0]["auto_correct"] is True


def test_employer_cannot_invite_unknown_candidate(client):
    emp = employer_with_company(client)
    assert _invite(client, emp, "C-0000000").status_code == 404
    # без профиля компании работодатель не может создавать потребности и приглашать
    other = register(client, "employer")
    assert client.get("/api/v1/employer/needs", headers=other.headers).status_code == 404


def test_access_is_limited_to_own_records(client):
    cand = graded_candidate(client, "backend", "middle")
    other_cand = register(client, "candidate")
    emp = employer_with_company(client)
    other_emp = employer_with_company(client, "ООО Чужая")
    need = create_need(client, emp)
    sel = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={}).json()
    inv = _invite(client, emp, public_id(client, cand)).json()
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    app_ = client.post("/api/v1/candidate/applications", headers=cand.headers, json={"need_id": need["id"]}).json()

    # другой кандидат не видит чужие приглашения и отклики
    assert client.get("/api/v1/candidate/invitations", headers=other_cand.headers).json() == []
    assert client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=other_cand.headers).status_code == 404
    assert client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=other_cand.headers, json={}).status_code == 404
    assert client.post("/api/v1/candidate/applications/%s/withdraw" % app_["id"], headers=other_cand.headers).status_code == 404
    # другая компания не видит чужие потребности, подборки, приглашения и отклики
    assert client.get("/api/v1/employer/needs/%s" % need["id"], headers=other_emp.headers).status_code == 404
    assert client.get("/api/v1/employer/selections/%s" % sel["id"], headers=other_emp.headers).status_code == 404
    assert client.get("/api/v1/employer/invitations/%s" % inv["id"], headers=other_emp.headers).status_code == 404
    assert client.get("/api/v1/employer/applications/%s" % app_["id"], headers=other_emp.headers).status_code == 404
    assert client.get("/api/v1/employer/invitations", headers=other_emp.headers).json() == []


def test_candidate_can_revoke_contact_access(client):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    cid = public_id(client, cand)
    inv = _invite(client, emp, cid).json()
    r = client.post("/api/v1/candidate/invitations/%s/revoke-contacts" % inv["id"], headers=cand.headers)
    assert r.json()["error"]["code"] == "contacts_not_shared", "до принятия отзывать нечего"
    client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=cand.headers, json={})
    assert client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).json()["contacts"] is not None
    r = client.post("/api/v1/candidate/invitations/%s/revoke-contacts" % inv["id"], headers=cand.headers).json()
    assert r["contacts_shared"] is False and r["timeline"][-1]["event"] == "contacts_revoked"
    assert client.get("/api/v1/employer/candidates/%s" % cid, headers=emp.headers).json()["contacts"] is None


def test_messaging_before_accept_keeps_contacts_hidden(client):
    cand = graded_candidate(client, "qa", "junior", stack=["sql"])
    emp = employer_with_company(client)
    cid = public_id(client, cand)
    inv = _invite(client, emp, cid).json()
    r = client.post("/api/v1/candidate/invitations/%s/messages" % inv["id"], headers=cand.headers,
                    json={"body": "Удалёнка возможна полностью?"})
    assert r.status_code == 201
    listed = client.get("/api/v1/employer/invitations/%s" % inv["id"], headers=emp.headers).json()
    assert listed["unread_messages"] == 1 and listed["contacts_visible"] is False
    thread = client.get("/api/v1/employer/invitations/%s/messages" % inv["id"], headers=emp.headers).json()
    assert thread[0]["body"] == "Удалёнка возможна полностью?" and thread[0]["sender"] == "candidate"
    client.post("/api/v1/employer/invitations/%s/messages" % inv["id"], headers=emp.headers, json={"body": "Да, полностью."})
    mine = client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=cand.headers).json()
    assert mine["unread_messages"] == 1
    # чужая переписка недоступна
    other = register(client, "candidate")
    assert client.get("/api/v1/candidate/invitations/%s/messages" % inv["id"], headers=other.headers).status_code == 404
    # после отказа переписка закрыта для новых сообщений
    client.post("/api/v1/candidate/invitations/%s/decline" % inv["id"], headers=cand.headers, json={"reason": "salary"})
    r = client.post("/api/v1/employer/invitations/%s/messages" % inv["id"], headers=emp.headers, json={"body": "А если выше?"})
    assert r.json()["error"]["code"] == "thread_closed"


def test_task_options_are_validated(client):
    emp = employer_with_company(client)
    body = {"title": "Задача", "body": "Выберите верный вариант ответа на вопрос", "kind": "choice", "specialization": "backend",
            "options": [{"text": "a"}, {"text": "b"}], "correct_option": "A"}
    assert client.post("/api/v1/employer/tasks", headers=emp.headers, json=body).status_code == 422
    foreign = create_need(client, employer_with_company(client, "ООО Чужая"))
    body.update(options=[{"id": "A", "text": "a"}, {"id": "B", "text": "b"}], need_id=foreign["id"])
    assert client.post("/api/v1/employer/tasks", headers=emp.headers, json=body).status_code == 404


def test_targeted_task_and_fair_distribution(client, db):
    emp = employer_with_company(client, "ООО Задачи")
    cand = graded_candidate(client, "backend", "middle")
    task = client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Подход к ретраям", "body": "Как повторить платёж при таймауте, не списав деньги дважды?",
        "kind": "approach", "specialization": "backend"}).json()
    r = client.post("/api/v1/employer/tasks/%s/assign" % task["id"], headers=emp.headers, json={"candidate_id": public_id(client, cand)})
    assert r.status_code == 201
    assert "Новое задание" in last_mail(client, cand.email) or "предлагает короткое задание" in last_mail(client, cand.email)
    again = client.post("/api/v1/employer/tasks/%s/assign" % task["id"], headers=emp.headers, json={"candidate_id": public_id(client, cand)})
    assert again.json()["error"]["code"] == "task_already_assigned"
    tasks = client.get("/api/v1/candidate/tasks", headers=cand.headers).json()
    assert any(t["task"]["title"] == "Подход к ретраям" for t in tasks)


def test_tasks_of_restricted_company_are_not_assigned(client, db):
    from app.services import tasks

    emp = employer_with_company(client, "ООО На проверке")
    client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Сколько запросов", "body": "Сколько запросов к базе выполнит цикл из 20 итераций?",
        "kind": "numeric", "specialization": "frontend", "correct_number": 21})
    company = db.scalar(select(Company).where(Company.name == "ООО На проверке"))
    company.review_status = "on_review"
    db.commit()
    cand = graded_candidate(client, "frontend", "middle")
    user = db.scalar(select(User).where(User.email == cand.email))
    assigned = tasks.assign_if_due(db, user)
    assert assigned is None or db.get(EmployerTask, assigned.task_id).company_id != company.id
    db.rollback()


def test_concurrent_task_offer_assigns_once_and_keeps_callers_work(client, db, monkeypatch):
    """Кабинет открыт в двух вкладках: оба запроса выбрали одно задание — выдаётся одно, письмо одно."""
    from sqlalchemy import delete

    from app.db import SessionLocal, utcnow
    from app.models import TaskAssignment
    from app.services import tasks

    emp = employer_with_company(client, "ООО Гонка")
    client.post("/api/v1/employer/tasks", headers=emp.headers, json={
        "title": "Двойное списание", "body": "Как не списать деньги дважды при повторе запроса?",
        "kind": "approach", "specialization": "backend"})
    cand = graded_candidate(client, "backend", "middle")
    user = db.scalar(select(User).where(User.email == cand.email))
    db.execute(delete(TaskAssignment).where(TaskAssignment.candidate_user_id == user.id))
    db.commit()
    mails_before = len(db.scalars(select(OutboxEmail).where(OutboxEmail.to_email == cand.email)).all())

    other = SessionLocal()
    real_begin_nested = db.begin_nested

    def racing(*args, **kwargs):
        # пока этот запрос выбирал задание, параллельный успел выдать то же самое
        assert tasks.assign_if_due(other, other.get(User, user.id)) is not None
        other.commit()
        return real_begin_nested(*args, **kwargs)

    monkeypatch.setattr(db, "begin_nested", racing)
    stamp = utcnow()
    user.last_login_at = stamp  # работа вызывающего, как при входе
    assert tasks.assign_if_due(db, user) is None
    db.commit()
    other.close()

    assert len(db.scalars(select(TaskAssignment).where(TaskAssignment.candidate_user_id == user.id)).all()) == 1
    assert len(db.scalars(select(OutboxEmail).where(OutboxEmail.to_email == cand.email)).all()) == mails_before + 1
    db.expire_all()
    assert db.get(User, user.id).last_login_at == stamp


def test_double_company_create_updates_instead_of_failing(client, db, monkeypatch):
    emp = employer_with_company(client, "ООО Двойной клик")
    miss_first_lookup(monkeypatch, "companies.owner_user_id")
    r = client.put("/api/v1/employer/company", headers=emp.headers,
                   json={"name": "ООО Двойной клик 2", "industry": "fintech", "city": "Казань"})
    assert r.status_code == 200 and r.json()["name"] == "ООО Двойной клик 2"
    assert len(db.scalars(select(Company).where(Company.name.like("ООО Двойной клик%"))).all()) == 1
