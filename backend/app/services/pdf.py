"""
Стандартизированный PDF-профиль кандидата.

Один и тот же шаблон для всех: категория и грейд, подтверждённые тестом
результаты, оценки компетенций с достоверностью, стек, опыт и достижения
ФСП. Для работодателя без раскрытых контактов профиль обезличен.
"""

import io
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import get_settings
from app.db import utcnow

BRAND = colors.HexColor("#1F3C88")
MUTED = colors.HexColor("#5B6475")

FONT_CANDIDATES = (
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
)


@lru_cache
def _fonts() -> tuple[str, str]:
    settings = get_settings()
    options = list(FONT_CANDIDATES)
    if settings.pdf_font_path:
        options.insert(0, (settings.pdf_font_path, settings.pdf_font_path))
    for regular, bold in options:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont("ProfileRegular", regular))
            pdfmetrics.registerFont(TTFont("ProfileBold", bold if Path(bold).exists() else regular))
            return "ProfileRegular", "ProfileBold"
    return "Helvetica", "Helvetica-Bold"  # без кириллицы: укажите APP_PDF_FONT_PATH


def _styles():
    regular, bold = _fonts()
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=18, leading=22, textColor=BRAND),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12, leading=16, textColor=BRAND, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13),
        "muted": ParagraphStyle("muted", fontName=regular, fontSize=8, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=9, leading=12),
        "cellb": ParagraphStyle("cellb", fontName=bold, fontSize=9, leading=12),
    }


def _table(rows, widths, styles):
    regular, _bold = _fonts()
    data = [[Paragraph(escape(str(c)), styles["cellb"] if i == 0 else styles["cell"]) for c in row] for i, row in enumerate(rows)]
    table = Table(data, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), regular),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF7")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D1E3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def render_profile(card: dict, generated_for: str) -> bytes:
    """card — карточка из app.services.cards.build_card(full=True)."""
    s = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = []
    category = card["category"]
    story.append(Paragraph(escape(card["display_name"]), s["title"]))
    story.append(
        Paragraph(
            "%s%s · грейд %s%s · профиль %s"
            % (
                category["specialization_title"],
                " · " + escape(category["track_title"]) if category.get("track_title") else "",
                category["level"],
                "" if category.get("confirmed", True) else " (не подтверждён тестом)",
                card["candidate_id"],
            ),
            s["body"],
        )
    )
    meta = []
    if card.get("city"):
        meta.append("Город: %s%s" % (escape(card["city"]), ", готов к переезду" if card.get("relocation") else ""))
    if card.get("experience_years") is not None:
        meta.append("Опыт: %s лет" % card["experience_years"])
    if card.get("work_formats"):
        meta.append("Формат: " + ", ".join(w["title"] for w in card["work_formats"]))
    if card.get("salary_expectation"):
        meta.append("Ожидания: от %s ₽" % format(card["salary_expectation"], ",").replace(",", " "))
    if meta:
        story.append(Paragraph(" · ".join(meta), s["muted"]))

    if card.get("contacts"):
        c = card["contacts"]
        story.append(Paragraph("Контакты", s["h2"]))
        story.append(Paragraph(escape(" · ".join(x for x in (c.get("full_name"), c.get("email"), c.get("phone"), c.get("telegram")) if x)), s["body"]))

    test = card["test"]
    story.append(Paragraph("Подтверждённый уровень", s["h2"]))
    story.append(
        Paragraph(
            "Тест уровня %s: %s баллов из 100. Оценка на заданиях уровня категории — %d%% "
            "(сглажена к среднему категории при малом числе заданий), сильнее %d%% кандидатов категории. "
            "Всего попыток: %s."
            % (
                (test.get("declared_level") or "—").capitalize(),
                test.get("score") if test.get("score") is not None else "—",
                round((test.get("level_band_rate") or 0) * 100),
                round((test.get("percentile_in_category") or 0) * 100),
                test.get("attempts_total"),
            ),
            s["body"],
        )
    )
    if card.get("competencies"):
        rows = [["Компетенция", "Оценка", "Сырая доля", "Заданий", "Достоверность"]]
        for comp in card["competencies"][:12]:
            rows.append(
                [comp["title"], "%d%%" % round(comp["estimate"] * 100), "%d%%" % round(comp["raw_rate"] * 100), comp["items"], comp["confidence_label"]]
            )
        story.append(Spacer(1, 4))
        story.append(_table(rows, [62 * mm, 25 * mm, 25 * mm, 20 * mm, 30 * mm], s))
        story.append(
            Paragraph(
                "Оценка сглажена: при малом числе заданий она приближена к общему уровню кандидата (см. документацию платформы).",
                s["muted"],
            )
        )
    if card.get("stack"):
        story.append(Paragraph("Стек (заявлено кандидатом)", s["h2"]))
        story.append(Paragraph(escape(", ".join(x["title"] for x in card["stack"])), s["body"]))
    if card.get("about"):
        story.append(Paragraph("О себе", s["h2"]))
        story.append(Paragraph(escape(card["about"]).replace("\n", "<br/>"), s["body"]))

    fsp = card.get("fsp") or {}
    story.append(Paragraph("Достижения ФСП", s["h2"]))
    if fsp.get("achievements"):
        rows = [["Мероприятие", "Дисциплина", "Уровень", "Итог", "Дата"]]
        for a in fsp["achievements"][:8]:
            rows.append([a["event_name"], a["discipline_title"], a["event_level_title"], a["result_title"], a["event_date"]])
        story.append(_table(rows, [64 * mm, 40 * mm, 30 * mm, 20 * mm, 18 * mm], s))
    elif fsp.get("hidden_by_candidate"):
        story.append(Paragraph("Кандидат скрыл достижения ФСП.", s["body"]))
    else:
        story.append(Paragraph("Истории в ФСП нет — это не влияет на остальные показатели профиля.", s["body"]))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Сформировано платформой подбора ИТ-специалистов %s для: %s. Категория и оценки получены по результатам "
            "тестирования на платформе, стек и опыт указаны кандидатом." % (utcnow().strftime("%d.%m.%Y %H:%M UTC"), escape(generated_for)),
            s["muted"],
        )
    )
    doc.build(story)
    return buffer.getvalue()
