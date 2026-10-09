"""152-ФЗ: согласия, выгрузка и удаление данных, публичные справочники и механика теста."""

import uuid

from sqlalchemy import select

from app.models import Application, Attempt, Company, OutboxEmail, Selection, User
from app.services.mailer import send_email
from tests.conftest import (
    PASSWORD,
    create_need,
    employer_with_company,
    graded_candidate,
    invite,
    public_id,
    publish_candidate,
    register,
    unique_email,
)


def test_data_export_contains_personal_data(client):
    acc = register(client)
    publish_candidate(client, acc, about="Люблю <b>теги</b> & амперсанды")
    data = client.get("/api/v1/candidate/data-export", headers=acc.headers).json()
    assert data["profile"]["full_name"] == "Петров Пётр Петрович"
    assert {c["kind"] for c in data["consents"]} >= {"pd_processing", "profile_publication"}
    # PDF-профиль доступен и до теста: категория «не присвоена», текст из профиля экранирован
    r = client.get("/api/v1/candidate/profile/pdf", headers=acc.headers)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_data_export_does_not_reveal_test(client, db):
    acc = graded_candidate(client, "qa", "junior", stack=["sql"])
    data = client.get("/api/v1/candidate/data-export", headers=acc.headers).json()
    attempt = data["attempts"][0]
    assert attempt["score"] is not None and attempt["result"]["competencies"]
    for hidden in ("seed", "keys", "items", "client_items"):
        assert hidden not in attempt
    assert "answers" not in attempt["result"] and "items" not in attempt["result"] and "seed" not in attempt["result"]
    seed = db.get(Attempt, uuid.UUID(attempt["id"])).seed
    assert str(seed) not in str(data)


def test_pdf_survives_markup_in_user_text(client):
    acc = graded_candidate(client, "backend", "junior", about="Люблю <b>теги</b> & <para>амперсанды</para>",
                           full_name="Иван <font> Тестов")
    pdf = client.get("/api/v1/candidate/profile/pdf", headers=acc.headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    emp = employer_with_company(client, "ООО <b>Разметка</b> & Ко")
    public_id = client.get("/api/v1/auth/me", headers=acc.headers).json()["public_id"]
    pdf = client.get("/api/v1/employer/candidates/%s/pdf" % public_id, headers=emp.headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_account_deletion_anonymizes(client):
    acc = register(client)
    publish_candidate(client, acc)
    assert client.delete("/api/v1/candidate/account", headers=acc.headers).status_code == 204
    r = client.post("/api/v1/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert r.status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": acc.tokens["refresh_token"]}).status_code == 401


def test_public_reference_and_test_mechanics(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    ref = client.get("/api/v1/reference").json()
    assert {s["slug"] for s in ref["specializations"]} == {"backend", "frontend", "qa"}
    preview = client.get("/api/v1/assessment/profiles/backend/middle").json()
    sizes = {v["points_total"] for v in preview["variants"]}
    assert len(sizes) == 1, "варианты теста сопоставимы по сумме баллов"
    assert preview["overlap_first_two"] < 0.6, "варианты различаются"
    demo = client.get("/api/v1/assessment/demo-vacancies").json()
    assert len(demo) == 6 and all(v["profile"]["competency_weights"] for v in demo)


def test_old_selection_does_not_keep_contacts_after_revoke_or_deletion(client, db):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    need = create_need(client, emp)
    inv = invite(client, emp, cand).json()
    client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=cand.headers, json={})
    sel = client.post("/api/v1/employer/needs/%s/selections" % need["id"], headers=emp.headers, json={}).json()
    pid = public_id(client, cand)
    row = next(r for r in sel["results"] if r["candidate_id"] == pid)
    assert row["candidate"]["contacts"]["phone"] == "+79000000001"
    # в базе подборки — только порядок и обоснование, без карточек и контактов
    stored = db.get(Selection, uuid.UUID(sel["id"]))
    assert "candidate" not in stored.results[0] and "+79000000001" not in str(stored.results)

    client.post("/api/v1/candidate/invitations/%s/revoke-contacts" % inv["id"], headers=cand.headers)
    again = client.get("/api/v1/employer/selections/%s" % sel["id"], headers=emp.headers).json()
    assert next(r for r in again["results"] if r["candidate_id"] == pid)["candidate"]["contacts"] is None

    assert client.delete("/api/v1/candidate/account", headers=cand.headers).status_code == 204
    after = client.get("/api/v1/employer/selections/%s" % sel["id"], headers=emp.headers).json()
    assert pid not in {r["candidate_id"] for r in after["results"]} and after["unavailable"] >= 1
    assert "+79000000001" not in str(after)


def test_hidden_fsp_is_not_ranked_explained_or_filterable(client):
    from tests.test_fsp import _authorize, _complete

    cand = graded_candidate(client, "frontend", "junior", stack=["react"])
    # FSP-100001 освобождается в test_fsp (привязка и отвязка); в конце тоже отвязываем
    assert _complete(client, cand, _authorize(client, cand, "FSP-100001")).status_code == 200
    emp = employer_with_company(client)
    pid = public_id(client, cand)

    def found(**flt):
        items = client.post("/api/v1/employer/candidates/search", headers=emp.headers,
                            json={"specialization": "frontend", "limit": 200, **flt}).json()["items"]
        return next((i for i in items if i["candidate"]["candidate_id"] == pid), None)

    visible = found()
    assert any("Всероссийские соревнования" in h for h in visible["ranking"]["highlights"])
    privacy = {"show_full_name": False, "show_city": True, "show_about": True, "show_fsp": False, "show_experience": True}
    client.put("/api/v1/candidate/privacy", headers=cand.headers, json=privacy)
    hidden = found()
    assert hidden["candidate"]["fsp"]["hidden_by_candidate"] is True
    assert not any("Всероссийские соревнования" in h for h in hidden["ranking"]["highlights"])
    fsp_factor = next(f for f in hidden["ranking"]["factors"] if f["factor"] == "fsp")
    assert fsp_factor["value"] == 0 and "скрыл" in fsp_factor["text"]
    assert found(has_fsp=True) is None, "фильтр не находит скрытые достижения"
    client.delete("/api/v1/candidate/fsp", headers=cand.headers)


def test_hidden_about_and_city_are_not_searchable(client):
    cand = graded_candidate(client, "qa", "junior", about="Люблю автоматизацию на Playwright", city="Казань", relocation=False)
    emp = employer_with_company(client)
    pid = public_id(client, cand)

    def ids(**flt):
        items = client.post("/api/v1/employer/candidates/search", headers=emp.headers,
                            json={"specialization": "qa", "limit": 200, **flt}).json()["items"]
        return {i["candidate"]["candidate_id"] for i in items}

    assert pid in ids(text="автоматизацию") and pid in ids(city="Казань")
    client.put("/api/v1/candidate/privacy", headers=cand.headers,
               json={"show_full_name": False, "show_city": False, "show_about": False, "show_fsp": True, "show_experience": True})
    assert pid not in ids(text="автоматизацию"), "поиск не идёт по скрытому разделу «о себе»"
    assert pid not in ids(city="Казань"), "скрытый город — неизвестный"


def test_candidate_deletion_erases_mail_copies_and_texts(client, db):
    cand = graded_candidate(client, "backend", "middle")
    emp = employer_with_company(client)
    need = create_need(client, emp)
    client.post("/api/v1/employer/needs/%s/publish" % need["id"], headers=emp.headers)
    client.post("/api/v1/candidate/applications", headers=cand.headers,
                json={"need_id": need["id"], "cover_letter": "Меня зовут Пётр, телефон +79000000001"})
    invite(client, emp, cand)
    assert db.scalars(select(OutboxEmail).where(OutboxEmail.to_email == cand.email)).first() is not None
    user_id = db.scalar(select(User.id).where(User.email == cand.email))
    assert client.delete("/api/v1/candidate/account", headers=cand.headers).status_code == 204
    db.expire_all()
    assert db.scalars(select(OutboxEmail).where(OutboxEmail.to_email == cand.email)).first() is None
    assert all(a.cover_letter is None for a in db.scalars(select(Application).where(Application.candidate_user_id == user_id)))


def test_employer_can_delete_account(client, db):
    emp = employer_with_company(client, "ООО Удаляемая")
    cand = graded_candidate(client, "backend", "middle")
    inv = invite(client, emp, cand).json()
    assert client.delete("/api/v1/employer/account", headers=emp.headers).status_code == 204
    seen = client.get("/api/v1/candidate/invitations/%s" % inv["id"], headers=cand.headers).json()
    assert seen["status"] == "withdrawn" and seen["company"]["name"] == "Компания удалила учётную запись"
    assert client.post("/api/v1/auth/login", json={"email": emp.email, "password": PASSWORD}).status_code == 401


def test_blocked_company_loses_candidate_data_and_its_invitations_cannot_be_accepted(client, db):
    emp = employer_with_company(client, "ООО Заблокированная")
    cand = graded_candidate(client, "backend", "middle")
    inv = invite(client, emp, cand).json()
    company = db.scalar(select(Company).where(Company.name == "ООО Заблокированная"))
    company.review_status = "blocked"
    db.commit()
    r = client.post("/api/v1/employer/candidates/search", headers=emp.headers, json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "company_blocked"
    assert client.get("/api/v1/employer/candidates/%s" % public_id(client, cand), headers=emp.headers).status_code == 403
    r = client.post("/api/v1/candidate/invitations/%s/accept" % inv["id"], headers=cand.headers, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "company_blocked"


def test_long_subject_is_truncated_to_column(db):
    mail = send_email(db, unique_email("x"), "Т" * 500, "текст")
    assert len(mail.subject) == 255
    db.rollback()
