"""
Тестовое PDF-резюме с вымышленными данными — для проверки распознавания
резюме (`POST /candidate/profile/resume`) без персональных данных
реальных людей.

Запуск (из каталога backend):
    python -m scripts.make_sample_resume            # samples/resume-demo.pdf
    python -m scripts.make_sample_resume --out файл.pdf

Каждая строка рисуется отдельно, чтобы текст извлекался из PDF так же,
как из резюме, выгруженного с сайтов вакансий.
"""

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from app.services.pdf import _fonts

ROOT = Path(__file__).resolve().parents[1]

# Все данные вымышлены: имя, контакты и компании не принадлежат реальным людям и организациям.
RESUME = [
    ("title", "Соколов Артём Игоревич"),
    ("subtitle", "Middle Python-разработчик (бэкенд)"),
    ("text", "г. Казань · готов к переезду · удалённо или гибрид"),
    ("text", "Телефон: +7 900 000-00-00"),
    ("text", "Почта: artem.sokolov@demo-fsp.ru"),
    ("text", "Telegram: @fsp_demo_candidate"),
    ("h2", "О себе"),
    ("text", "Бэкенд-разработчик, опыт работы 4 года. Проектирую REST API и микросервисы, отвечаю за "
             "надёжность платёжных сценариев: идемпотентность, повторы, очереди. Работаю наставником "
             "для стажёров, люблю разбирать инциденты и писать понятную документацию."),
    ("h2", "Опыт работы"),
    ("text", "2022 — н. в. · ООО «Вымышленный платёжный сервис» · Python-разработчик"),
    ("text", "FastAPI, PostgreSQL, Redis, Kafka. Перевёл обработку платежей на очереди и сократил "
             "время ответа API в 3 раза; внедрил идемпотентные ключи и ретраи без двойных списаний."),
    ("text", "2020 — 2022 · ООО «Условная логистика» · младший разработчик"),
    ("text", "Django, REST API, Celery, Docker. Интеграции с партнёрами, отчёты, покрытие тестами pytest."),
    ("h2", "Навыки"),
    ("text", "Python, FastAPI, Django, PostgreSQL, SQL, Redis, Kafka, RabbitMQ, Docker, Kubernetes, Linux, "
             "Git, CI/CD, REST API, gRPC, микросервисы, pytest"),
    ("h2", "Роль в команде"),
    ("text", "Разработчик, наставник для стажёров"),
    ("h2", "Личные качества"),
    ("text", "Коммуникабельность, работа в команде, ответственность, обучаемость, аналитическое мышление"),
    ("h2", "Достижения"),
    ("text", "Призёр всероссийских соревнований по продуктовому программированию (ФСП), 2024"),
    ("h2", "Образование"),
    ("text", "Условный технический университет, прикладная информатика, 2020"),
    ("note", "Тестовое резюме с вымышленными данными для проверки распознавания на платформе подбора ФСП."),
]

STYLE = {
    "title": (16, True, "#402FFF", 22),
    "subtitle": (11, True, "#1B1C21", 18),
    "h2": (11, True, "#402FFF", 20),
    "text": (9.5, False, "#1B1C21", 13),
    "note": (7.5, False, "#7A7C85", 12),
}


def build(out: Path) -> Path:
    regular, bold = _fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(out), pagesize=A4)
    pdf.setTitle("Тестовое резюме")
    pdf.setAuthor("Демо-данные платформы подбора ФСП")
    width, height = A4
    left, right, y = 50, width - 50, height - 60
    for kind, text in RESUME:
        size, is_bold, color, leading = STYLE[kind]
        font = bold if is_bold else regular
        if kind == "h2":
            y -= 6
        if kind == "note":
            y = min(y, 60)
        for line in simpleSplit(text, font, size, right - left):
            pdf.setFont(font, size)
            pdf.setFillColor(HexColor(color))
            pdf.drawString(left, y, line)
            y -= leading
    pdf.save()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Тестовое PDF-резюме с вымышленными данными")
    parser.add_argument("--out", default=str(ROOT / "samples" / "resume-demo.pdf"))
    path = build(Path(parser.parse_args().out))
    print(path)


if __name__ == "__main__":
    main()
