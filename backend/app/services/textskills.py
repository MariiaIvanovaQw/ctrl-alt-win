"""
Извлечение навыков и упоминаний компетенций из текста.

Правиловый разбор по таксономии (app/reference.py): синонимы на русском
и английском, учёт словоформ через поиск по началу слова. Он объясним
(видно, какое слово дало навык), работает без внешних сервисов и не
отправляет персональные данные резюме третьим лицам, что важно для
152-ФЗ. Модель на эмбеддингах можно добавить вторым этапом за тем же
интерфейсом.
"""

import re
from functools import lru_cache

from app.reference import COMPETENCY_KEYWORDS, SKILLS


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _compile(alias: str) -> re.Pattern:
    alias = normalize(alias)
    prefix = alias.endswith("*")
    core = re.escape(alias.rstrip("*"))
    left = r"(?<![a-zа-я0-9])"
    right = "" if prefix else r"(?![a-zа-я0-9+#])"
    return re.compile(left + core + right)


@lru_cache
def _skill_patterns() -> dict[str, list[tuple[str, re.Pattern]]]:
    return {slug: [(alias, _compile(alias)) for alias in aliases] for slug, (_title, aliases, _map) in SKILLS.items()}


@lru_cache
def _keyword_patterns() -> dict[str, dict[str, list[re.Pattern]]]:
    return {
        spec: {comp: [_compile(word) for word in words] for comp, words in comps.items()}
        for spec, comps in COMPETENCY_KEYWORDS.items()
    }


def extract_skills(text: str) -> list[dict]:
    """Навыки из текста в порядке первого упоминания, с найденными словами."""
    norm = normalize(text)
    found = []
    for slug, patterns in _skill_patterns().items():
        first = None
        matched = []
        for alias, pattern in patterns:
            m = pattern.search(norm)
            if m:
                matched.append(alias.rstrip("*"))
                first = m.start() if first is None else min(first, m.start())
        if matched:
            found.append({"slug": slug, "title": SKILLS[slug][0], "matched": matched, "position": first})
    found.sort(key=lambda x: x["position"])
    return found


def competency_mentions(text: str, specialization: str) -> dict[str, int]:
    norm = normalize(text)
    counts = {}
    for comp, patterns in _keyword_patterns().get(specialization, {}).items():
        n = sum(len(p.findall(norm)) for p in patterns)
        if n:
            counts[comp] = n
    return counts


def skill_competencies(slug: str, specialization: str) -> list[str]:
    entry = SKILLS.get(slug)
    if not entry:
        return []
    return list(entry[2].get(specialization, []))
