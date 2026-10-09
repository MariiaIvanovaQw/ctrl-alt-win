"""
Распознавание PDF-резюме.

Текст извлекается из PDF (pypdf), затем поля ищутся правилами: ФИО,
контакты, город, стаж (по фразе «опыт работы N лет» или сумме периодов
работы), грейд, роли, специализация, навыки по таксономии и софт-скиллы.
Результат — подсказки с уровнем уверенности: профиль не перезаписывается
автоматически, кандидат подтверждает поля сам. Резюме обрабатывается
локально и никуда не передаётся (152-ФЗ).
"""

import io
import re
from datetime import datetime, timezone

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.errors import AppError
from app.reference import SOFT_SKILLS, SPECIALIZATIONS
from app.services.textskills import extract_skills, normalize

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
# «@ник» засчитывается, только если это не часть адреса почты (перед @ нет символов адреса)
TG_RE = re.compile(r"(?:t\.me/|telegram[:\s]+@?|(?<![\w.+-])@)([A-Za-z][A-Za-z0-9_]{4,31})", re.IGNORECASE)
NAME_RE = re.compile(r"^([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ][а-яё]+)(?:\s+([А-ЯЁ][а-яё]+))?$")
EXPERIENCE_RE = re.compile(r"опыт работы[^\d]{0,15}(\d{1,2})\s*(?:год|лет)(?:[^\d]{0,5}(\d{1,2})\s*месяц)?")
PERIOD_RE = re.compile(
    r"((?:19|20)\d{2})\s*[—–-]\s*((?:19|20)\d{2}|н\.?\s*в\.?|настоящее время|по настоящее время|сейчас|present)",
)
CITY_RE = re.compile(r"(?:город|г\.)\s*:?\s*([А-ЯЁ][а-яё]+(?:[\s-][А-ЯЁ][а-яё]+)?)")
KNOWN_CITIES = (
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Челябинск",
    "Самара", "Омск", "Ростов-на-Дону", "Уфа", "Красноярск", "Пермь", "Воронеж", "Волгоград", "Краснодар",
    "Томск", "Иннополис", "Калининград", "Тюмень",
)
LEVEL_WORDS = {
    "senior": ("senior", "ведущий", "старший"),
    "middle": ("middle", "мидл"),
    "junior": ("junior", "джуниор", "младший", "стажер", "стажёр", "intern"),
}
ROLE_WORDS = {
    "team_lead": ("тимлид", "team lead", "teamlead", "руководитель группы"),
    "tech_lead": ("техлид", "tech lead", "техлидер"),
    "architect": ("архитектор", "architect"),
    "qa_automation": ("автоматизатор", "qa automation", "aqa", "автоматизации тестирования"),
    "qa_manual": ("тестировщик", "ручное тестирование", "manual qa"),
    "mentor": ("наставник", "ментор", "mentor"),
    "developer": ("разработчик", "developer", "программист", "engineer"),
}
SPEC_WORDS = {
    "backend": ("backend", "бэкенд", "бекенд", "back-end", "серверн"),
    "frontend": ("frontend", "фронтенд", "front-end", "верстальщик", "react-разработчик"),
    "qa": ("qa", "тестировщик", "тестирован", "quality assurance"),
}


def extract_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AppError("Резюме защищено паролем", code="resume_encrypted")
        return "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except (PdfReadError, ValueError, KeyError) as exc:
        raise AppError("Не удалось прочитать PDF", code="resume_unreadable") from exc


def _field(value, confidence: float, source: str | None = None) -> dict:
    return {"value": value, "confidence": round(confidence, 2), "source": source}


def _experience(text: str, norm: str) -> dict | None:
    m = EXPERIENCE_RE.search(norm)
    if m:
        years = int(m.group(1)) + (int(m.group(2)) / 12 if m.group(2) else 0)
        return _field(round(years, 1), 0.9, m.group(0))
    total = 0
    spans = []
    this_year = datetime.now(timezone.utc).year
    for start, end in PERIOD_RE.findall(norm):
        end_year = int(end) if end[:2] in ("19", "20") else this_year
        if int(start) <= end_year <= this_year:
            total += end_year - int(start)
            spans.append("%s–%s" % (start, end_year))
    if total:
        return _field(float(total), 0.6, ", ".join(spans))
    return None


def parse_resume(data: bytes) -> dict:
    text = extract_text(data)
    if len(text.strip()) < 30:
        raise AppError("В PDF не найден текст: возможно, это скан. Заполните профиль вручную", code="resume_no_text")
    norm = normalize(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict = {"characters": len(text)}

    for line in lines[:8]:
        m = NAME_RE.match(line)
        if m:
            result["full_name"] = _field(line, 0.8, line)
            break
    if m := EMAIL_RE.search(text):
        result["contact_email"] = _field(m.group(0).lower(), 0.95, m.group(0))
    if m := PHONE_RE.search(text):
        digits = re.sub(r"\D", "", m.group(0))
        result["phone"] = _field("+7" + digits[-10:], 0.9, m.group(0))
    if m := TG_RE.search(text):
        result["telegram"] = _field("@" + m.group(1), 0.8, m.group(0))
    city = None
    if m := CITY_RE.search(text):
        city = _field(m.group(1), 0.8, m.group(0))
    else:
        for name in KNOWN_CITIES:
            if name.lower() in norm:
                city = _field(name, 0.5, name)
                break
    if city:
        result["city"] = city
    if exp := _experience(text, norm):
        result["experience_years"] = exp

    for level, words in LEVEL_WORDS.items():
        hit = next((w for w in words if re.search(r"(?<![a-zа-я])" + re.escape(w), norm)), None)
        if hit:
            result["level_hint"] = _field(level, 0.6, hit)
            break
    roles = [role for role, words in ROLE_WORDS.items() if any(w in norm for w in words)]
    if roles:
        result["roles"] = _field(roles, 0.6)
    spec_scores = {spec: sum(norm.count(w) for w in words) for spec, words in SPEC_WORDS.items()}
    best = max(spec_scores, key=spec_scores.get)
    if spec_scores[best]:
        result["specialization"] = _field(best, min(0.9, 0.4 + 0.1 * spec_scores[best]), SPECIALIZATIONS[best])
    skills = extract_skills(text)
    if skills:
        result["stack"] = _field([s["slug"] for s in skills], 0.8, ", ".join(s["title"] for s in skills[:12]))
    soft = [slug for slug, (_title, words) in SOFT_SKILLS.items() if any(w in norm for w in words)]
    if soft:
        result["soft_skills"] = _field(soft, 0.5)
    return result
