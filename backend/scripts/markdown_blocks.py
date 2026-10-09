"""
Разбор Markdown пояснительной записки на блоки для сборки PDF и DOCX.

Поддерживается подмножество, которое используется в docs/documentation.md:
заголовки, абзацы, списки (в том числе вложенные), таблицы, блоки кода,
цитаты; внутри строк – **полужирный**, `код` и [ссылки](адрес).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs" / "documentation.md"
TITLE = "Цифровая платформа подбора ИТ-специалистов с верифицированным профилем ФСП"
SUBTITLE = "Пояснительная записка"
FOOTER = "Платформа подбора ИТ-специалистов ФСП – пояснительная записка"

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
LIST_RE = re.compile(r"^(\s*)([*-]|\d+\.)\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
TABLE_RULE_RE = re.compile(r":?-{2,}:?")


@dataclass
class Block:
    kind: str  # heading | paragraph | list | table | code | quote
    text: str = ""
    level: int = 0
    rows: list = field(default_factory=list)  # таблица: строки ячеек; список: (уровень, маркер, текст)


def split_row(line: str) -> list[str]:
    """Строка таблицы → ячейки; «|» внутри `кода` и экранированный «\\|» ячейку не делят."""
    line = line.strip().strip("|")
    cells, buf, in_code = [], "", False
    for i, ch in enumerate(line):
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code and (i == 0 or line[i - 1] != "\\"):
            cells.append(buf.strip())
            buf = ""
        else:
            buf += ch
    cells.append(buf.strip())
    return [c.replace("\\|", "|") for c in cells]


def parse_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    lines = text.splitlines()
    paragraph: list[str] = []
    items: list[tuple[int, str, str]] = []

    def flush():
        if paragraph:
            blocks.append(Block("paragraph", " ".join(s.strip() for s in paragraph)))
            paragraph.clear()
        if items:
            blocks.append(Block("list", rows=list(items)))
            items.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip().startswith("```")), len(lines))
            blocks.append(Block("code", "\n".join(lines[i + 1:end])))
            i = end + 1
            continue
        if stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = split_row(lines[i])
                if not all(TABLE_RULE_RE.fullmatch(c) for c in row if c):
                    rows.append(row)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                blocks.append(Block("table", rows=[r + [""] * (width - len(r)) for r in rows]))
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            flush()
            blocks.append(Block("heading", heading.group(2), level=min(len(heading.group(1)), 3)))
            i += 1
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(Block("quote", " ".join(quote)))
            continue
        item = LIST_RE.match(line)
        if item:
            if paragraph:
                blocks.append(Block("paragraph", " ".join(s.strip() for s in paragraph)))
                paragraph.clear()
            level = len(item.group(1).replace("\t", "  ")) // 2
            items.append((min(level, 3), item.group(2), item.group(3)))
        elif items and line.startswith("  ") and stripped:
            level, marker, previous = items[-1]  # продолжение пункта списка на следующей строке
            items[-1] = (level, marker, previous + " " + stripped)
        elif not stripped or stripped in ("---", "***"):
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if not (items and (LIST_RE.match(next_line) or next_line.startswith("  "))):
                flush()
        else:
            if items:
                flush()
            paragraph.append(line)
        i += 1
    flush()
    return blocks


def sections(path: Path = SOURCE) -> list[tuple[str, list[Block]]]:
    """Записка по разделам первого уровня: (заголовок, блоки раздела вместе с заголовком)."""
    result: list[tuple[str, list[Block]]] = []
    for block in parse_blocks(path.read_text(encoding="utf-8")):
        if block.kind == "heading" and block.level == 1:
            result.append((block.text, []))
        if result:
            result[-1][1].append(block)
    return result
