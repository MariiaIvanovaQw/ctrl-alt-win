"""
Сборка пояснительной записки docs/documentation.md в PDF (ТЗ, раздел 5.2:
документация в формате doc или pdf).

Запуск (из каталога backend):
    python -m scripts.build_docs          # docs/documentation.pdf
"""

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

from scripts.markdown_blocks import BOLD, FOOTER, INLINE_CODE, LINK, REPO, SUBTITLE, TITLE, Block, sections

BRAND = colors.HexColor("#402FFF")  # фиолетовый из брендбука ФСП
LINK_COLOR = "#1F3C88"
MARGIN = 18 * mm
FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/consola.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
]


def register_fonts() -> tuple[str, str, str]:
    for regular, bold, mono in FONT_CANDIDATES:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont("DocRegular", regular))
            pdfmetrics.registerFont(TTFont("DocBold", bold if Path(bold).exists() else regular))
            pdfmetrics.registerFont(TTFont("DocMono", mono if Path(mono).exists() else regular))
            pdfmetrics.registerFontFamily("DocRegular", normal="DocRegular", bold="DocBold",
                                          italic="DocRegular", boldItalic="DocBold")
            return "DocRegular", "DocBold", "DocMono"
    raise SystemExit("Не найден шрифт с кириллицей (Arial или DejaVu)")


def styles(regular: str, bold: str, mono: str) -> dict:
    base = {"fontName": regular, "fontSize": 9.5, "leading": 13.5}
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=22, leading=28, textColor=BRAND, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", fontName=regular, fontSize=12, leading=16, alignment=TA_CENTER),
        1: ParagraphStyle("h1", fontName=bold, fontSize=15, leading=20, textColor=BRAND, spaceBefore=12, spaceAfter=7,
                          keepWithNext=True),
        2: ParagraphStyle("h2", fontName=bold, fontSize=12, leading=16, textColor=BRAND, spaceBefore=9, spaceAfter=4,
                          keepWithNext=True),
        3: ParagraphStyle("h3", fontName=bold, fontSize=10.5, leading=14, spaceBefore=7, spaceAfter=3, keepWithNext=True),
        "body": ParagraphStyle("body", spaceAfter=5, **base),
        "quote": ParagraphStyle("quote", leftIndent=10, borderPadding=(4, 6, 4, 6), backColor=colors.HexColor("#F1F4FA"),
                                spaceAfter=6, spaceBefore=2, **base),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=8, leading=10.5),
        "cellb": ParagraphStyle("cellb", fontName=bold, fontSize=8, leading=10.5),
        "code": ParagraphStyle("code", fontName=mono, fontSize=7.3, leading=9.2, backColor=colors.HexColor("#F5F6F8"),
                               borderPadding=4, spaceBefore=3, spaceAfter=7),
        "toc": ParagraphStyle("toc", fontName=regular, fontSize=10.5, leading=16),
        "mono": mono,
    }


def inline(text: str, mono: str) -> str:
    """Строка Markdown → разметка Paragraph ReportLab (с экранированием)."""
    out = []
    last = 0
    for m in INLINE_CODE.finditer(text):
        out.append(_plain(text[last:m.start()]))
        out.append("<font face='%s' color='%s'>%s</font>" % (mono, LINK_COLOR, escape(m.group(1))))
        last = m.end()
    out.append(_plain(text[last:]))
    return "".join(out)


def _plain(text: str) -> str:
    text = escape(text)
    text = LINK.sub(lambda m: "<link href='%s' color='%s'>%s</link>" % (m.group(2), LINK_COLOR, m.group(1))
                    if m.group(2).startswith("http") else m.group(1), text)
    return BOLD.sub(r"<b>\1</b>", text)


def table_flowable(rows: list[list[str]], st: dict, width: float) -> Table:
    ncols = len(rows[0])
    # ширина столбцов пропорциональна длине текста, но не уже 18 мм
    lengths = [max(min(len(r[i]), 60) for r in rows) + 4 for i in range(ncols)]
    widths = [max(18 * mm, width * n / sum(lengths)) for n in lengths]
    widths = [w * width / sum(widths) for w in widths]
    data = [[Paragraph(inline(c, st["mono"]), st["cellb"] if i == 0 else st["cell"]) for c in r] for i, r in enumerate(rows)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF7")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D1E3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def flowables(blocks: list[Block], st: dict, width: float) -> list:
    flow: list = []
    for block in blocks:
        if block.kind == "heading":
            flow.append(Paragraph(inline(block.text, st["mono"]), st[block.level]))
        elif block.kind == "paragraph":
            flow.append(Paragraph(inline(block.text, st["mono"]), st["body"]))
        elif block.kind == "quote":
            flow.append(Paragraph(inline(block.text, st["mono"]), st["quote"]))
        elif block.kind == "code":
            flow.append(Preformatted(block.text, st["code"], maxLineLength=118, newLineChars=""))
        elif block.kind == "table":
            flow += [table_flowable(block.rows, st, width), Spacer(1, 6)]
        elif block.kind == "list":
            for level, marker, text in block.rows:
                bullet = marker if marker[0].isdigit() else ("•" if level == 0 else "–")
                style = ParagraphStyle("li%d" % level, parent=st["body"], leftIndent=12 + 12 * level,
                                       bulletIndent=2 + 12 * level, spaceAfter=2)
                flow.append(Paragraph(inline(text, st["mono"]), style, bulletText=bullet))
            flow.append(Spacer(1, 3))
    return flow


def build_pdf(parts: list[tuple[str, list[Block]]], out: Path, date_text: str) -> None:
    regular, bold, mono = register_fonts()
    st = styles(regular, bold, mono)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="%s – %s" % (TITLE, SUBTITLE.lower()))
    width = A4[0] - 2 * MARGIN
    story = [
        Spacer(1, 60 * mm),
        Paragraph(TITLE, st["title"]),
        Spacer(1, 8 * mm),
        Paragraph(SUBTITLE, st["subtitle"]),
        Spacer(1, 4 * mm),
        Paragraph(date_text, st["subtitle"]),
        PageBreak(),
        Paragraph("Содержание", st[1]),
    ]
    story += [Paragraph(escape(title), st["toc"]) for title, _blocks in parts]
    story.append(PageBreak())
    for _title, blocks in parts:
        story += flowables(blocks, st, width)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(colors.HexColor("#5B6475"))
        canvas.drawString(MARGIN, 9 * mm, FOOTER)
        canvas.drawRightString(A4[0] - MARGIN, 9 * mm, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=footer)


def main() -> None:
    out = REPO / "docs" / "documentation.pdf"
    build_pdf(sections(), out, datetime.now(timezone.utc).strftime("%d.%m.%Y"))
    print("%s: %d КБ" % (out.relative_to(REPO).as_posix(), out.stat().st_size // 1024))


if __name__ == "__main__":
    main()
