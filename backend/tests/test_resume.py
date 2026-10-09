"""Распознавание PDF-резюме: ФИО, контакты, стек, грейд, роли, стаж, софт-скиллы."""

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.services.pdf import _fonts
from tests.conftest import register

RESUME = [
    "Соколова Анна Игоревна",
    "Middle бэкенд-разработчик",
    "Email: anna.sokolova@example.com  Телефон: +7 (912) 345-67-89  Telegram: @anna_dev",
    "Город: Казань",
    "Опыт работы 4 года 6 месяцев",
    "Стек: Python, FastAPI, PostgreSQL, Redis, Docker, Kafka",
    "2022 — настоящее время: разработчик платёжного сервиса, наставник стажёров",
    "Качества: ответственность, работа в команде, коммуникабельность",
]


def _pdf(lines: list[str]) -> bytes:
    regular, _bold = _fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont(regular, 11)
    y = 800
    for line in lines:
        c.drawString(40, y, line)
        y -= 18
    c.save()
    return buffer.getvalue()


def test_resume_recognition_and_apply(client):
    acc = register(client)
    r = client.post("/api/v1/candidate/profile/resume", headers=acc.headers,
                    files={"file": ("resume.pdf", _pdf(RESUME), "application/pdf")})
    assert r.status_code == 200, r.text
    s = r.json()["suggestions"]
    assert s["full_name"]["value"] == "Соколова Анна Игоревна"
    assert s["contact_email"]["value"] == "anna.sokolova@example.com"
    assert s["phone"]["value"] == "+79123456789"
    assert s["telegram"]["value"] == "@anna_dev"
    assert s["city"]["value"] == "Казань"
    assert s["experience_years"]["value"] == 4.5
    assert s["level_hint"]["value"] == "middle"
    assert s["specialization"]["value"] == "backend"
    assert {"python", "fastapi", "postgresql", "redis", "docker", "kafka"} <= set(s["stack"]["value"])
    assert {"developer", "mentor"} <= set(s["roles"]["value"])
    assert s["soft_skills"]["value"], "софт-скиллы распознаны"
    # подсказки не перезаписывают профиль сами — только после подтверждения
    assert client.get("/api/v1/candidate/profile", headers=acc.headers).json()["full_name"] is None
    r = client.post("/api/v1/candidate/profile/resume/apply", headers=acc.headers,
                    json={"fields": ["full_name", "phone", "city", "stack", "experience_years"]})
    profile = r.json()
    assert profile["full_name"] == "Соколова Анна Игоревна" and profile["city"] == "Казань"
    assert "kafka" in profile["stack"] and profile["experience_years"] == 4.5


def test_resume_rejects_non_pdf_and_scans(client):
    acc = register(client)
    r = client.post("/api/v1/candidate/profile/resume", headers=acc.headers,
                    files={"file": ("resume.txt", b"plain text", "text/plain")})
    assert r.json()["error"]["code"] == "not_pdf"
    r = client.post("/api/v1/candidate/profile/resume", headers=acc.headers,
                    files={"file": ("scan.pdf", _pdf([]), "application/pdf")})
    assert r.json()["error"]["code"] == "resume_no_text"


def test_sample_resume_is_fully_recognized():
    """samples/resume-demo.pdf — вымышленное резюме для демонстрации; все поля должны распознаваться."""
    from pathlib import Path

    from app.services.resume import parse_resume

    sample = Path(__file__).resolve().parents[1] / "samples" / "resume-demo.pdf"
    result = parse_resume(sample.read_bytes())
    assert result["full_name"]["value"] == "Соколов Артём Игоревич"
    assert result["contact_email"]["value"].endswith("@demo-fsp.ru")
    assert result["city"]["value"] == "Казань" and result["specialization"]["value"] == "backend"
    assert result["level_hint"]["value"] == "middle" and result["experience_years"]["value"] == 4
    assert {"python", "fastapi", "postgresql"} <= set(result["stack"]["value"])
