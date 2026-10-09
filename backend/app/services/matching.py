"""
Подбор и ранжирование кандидатов.

Два режима:

1. Просмотр категории (специализация + грейд). Порядок внутри категории
   задаёт сила подтверждённого профиля:
       0,60 · сила теста + 0,25 · ФСП + 0,15 · свежесть

2. Подбор под потребность работодателя. Кандидаты берутся из категорий,
   подходящих потребности, и ранжируются по соответствию:
       0,35 · компетенции + 0,25 · сила теста + 0,15 · стек
       + 0,15 · ФСП + 0,10 · свежесть,
   затем умножаются на (1 − поправка на условия: зарплата, формат, город).

Кандидаты, прошедшие опрос, но без подтверждённого тестом грейда, тоже
видны (уточнение постановщиков: «показывать со статусом и опускать в
выдаче, не скрывать»): у них заявленный уровень, статус «не подтверждён»,
нулевая сила теста, и в любой выдаче они идут после подтверждённых.

Категорию определяет только тест, а не текст резюме. Самоописанные
данные (стек, ожидания) участвуют лишь как уточнение и всегда помечены в
объяснении как «заявлено кандидатом». Заявленный навык засчитывается
полностью, только если связанная с ним компетенция подтверждена тестом
(оценка не ниже 50 %), иначе — наполовину: отметить «все навыки» не
выгодно.

Настройки приватности соблюдаются и в ранжировании: скрытые кандидатом
достижения ФСП не дают бонуса и не попадают в объяснение (иначе
объяснение раскрыло бы их), скрытый город считается неизвестным.

Сила теста сравнима между кандидатами, проходившими тесты разных уровней:
берётся доля баллов на заданиях полос сложности, соответствующих
категории (junior — d1–3 и d4–6, middle — d4–6 и d7–8, senior — d7–8 и
d9–10), и её место среди кандидатов той же категории.

Доля по полосе сглаживается к среднему по категории так же, как оценки
компетенций: (баллы + K · среднее) / (возможные + K). Иначе кандидат,
получивший категорию middle по тесту junior, выглядел бы сильнейшим:
в тесте junior заданий d7–8 нет, а несколько лёгких заданий d4–6 дают
«100 %». При сглаживании отсутствующая полоса оценивается средним по
категории, а малое число заданий почти не сдвигает оценку от него.
"""

import math
import threading
import time
import uuid
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.db import utcnow
from app.models import (
    Attempt,
    CandidateGrade,
    CandidateProfile,
    CompetencyEstimate,
    Consent,
    FspAchievement,
    FspLink,
    GradeRecommendation,
    Survey,
    TaskAssignment,
    User,
)
from app.reference import COMPETENCY_TITLES, LEVEL_INDEX, LEVELS, SKILLS, SPECIALIZATIONS, WORK_FORMATS
from app.services import fsp as fsp_service
from app.services import minors
from app.services.textskills import skill_competencies

NEED_WEIGHTS = {"competencies": 0.35, "test": 0.25, "stack": 0.15, "fsp": 0.15, "freshness": 0.10}
CATEGORY_WEIGHTS = {"test": 0.60, "fsp": 0.25, "freshness": 0.15}
FACTOR_TITLES = {
    "competencies": "Компетенции под задачу",
    "test": "Результат теста",
    "stack": "Стек (заявлено кандидатом)",
    "fsp": "Достижения ФСП",
    "freshness": "Актуальность профиля",
}

# Полосы сложности, по которым измеряется уровень категории, и их веса.
CATEGORY_BANDS = {
    "junior": (("easy", 0.6), ("mid", 0.4)),
    "middle": (("mid", 0.6), ("hard", 0.4)),
    "senior": (("hard", 0.6), ("top", 0.4)),
}
BAND_TITLES = {"easy": "d1–3", "mid": "d4–6", "hard": "d7–8", "top": "d9–10"}
# псевдобаллы сглаживания (≈ три задания) и среднее по полосе, пока в
# категории мало измерений
BAND_PRIOR_POINTS = 6.0
BAND_PRIOR_MIN_CANDIDATES = 5
DEFAULT_BAND_PRIOR = {"easy": 0.8, "mid": 0.6, "hard": 0.4, "top": 0.3}

PENALTY_SALARY = 0.15
PENALTY_FORMAT = 0.10
PENALTY_CITY = 0.10
# заявленный навык без подтверждения тестом связанной компетенции
UNCONFIRMED_SKILL = 0.5
SKILL_CONFIRMED_AT = 0.5
FSP_HIDDEN_TEXT = "Кандидат скрыл достижения ФСП — фактор не учитывается"


CLAIM_STATUS_TITLES = {
    "not_tested": "тест ещё не пройден",
    "not_confirmed": "тест не подтвердил заявленный уровень",
    "decision_pending": "кандидат решает, принять ли рекомендованный уровень",
}


@dataclass
class ClaimedGrade:
    """Заявленный в опросе, но не подтверждённый тестом грейд."""

    user_id: uuid.UUID
    specialization: str
    level: str
    status: str
    assigned_at: datetime | None = None
    last_change_at: datetime | None = None
    defining_attempt_id: uuid.UUID | None = None
    confirmed: bool = False


def is_confirmed(grade) -> bool:
    return bool(getattr(grade, "confirmed", True))


@dataclass
class Facts:
    user: User
    profile: CandidateProfile
    grade: CandidateGrade
    attempt: Attempt | None
    attempts_count: int = 0
    estimates: dict[str, CompetencyEstimate] = field(default_factory=dict)
    achievements: list[FspAchievement] = field(default_factory=list)
    fsp_linked: bool = False
    fsp_rank: str | None = None
    tasks_solved: int = 0
    tasks_quality: float = 0.0
    last_task_at: datetime | None = None
    band_rate: float = 0.0
    band_detail: list = field(default_factory=list)
    percentile: float = 0.5
    fsp: dict = field(default_factory=dict)

    @property
    def overall_rate(self) -> float:
        earned = sum(e.earned for e in self.estimates.values())
        possible = sum(e.possible for e in self.estimates.values())
        return earned / possible if possible else 0.5


# ------------------------------------------------------------------ загрузка


def _published(db: Session, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Кандидаты с действующим согласием на показ профиля работодателям."""
    if not user_ids:
        return set()
    latest = (
        select(Consent.user_id, func.max(Consent.created_at).label("at"))
        .where(Consent.kind == "profile_publication", Consent.user_id.in_(user_ids))
        .group_by(Consent.user_id)
        .subquery()
    )
    rows = db.execute(
        select(Consent.user_id, Consent.granted).join(
            latest, (Consent.user_id == latest.c.user_id) & (Consent.created_at == latest.c.at)
        ).where(Consent.kind == "profile_publication")
    )
    return {uid for uid, granted in rows if granted}


# Подбору нужны только эти поля попытки; тяжёлые JSON (задания, ключи,
# полный результат) не загружаются — на сотнях кандидатов это основная
# часть времени ответа.
ATTEMPT_FIELDS = (Attempt.id, Attempt.user_id, Attempt.specialization, Attempt.declared_level, Attempt.score,
                  Attempt.finished_at, Attempt.summary)


def attempt_summary(attempt) -> dict:
    return (getattr(attempt, "summary", None) or {}) if attempt is not None else {}


def _band_points(attempt: Attempt | None) -> dict[str, tuple[float, float]]:
    buckets = attempt_summary(attempt).get("difficulty_buckets") or {}
    return {band: (data.get("points_earned") or 0, data.get("points_possible") or 0) for band, data in buckets.items()}


def band_priors(attempts: list[Attempt | None]) -> dict[str, float]:
    """Средняя доля баллов по полосам у кандидатов категории (по баллам, не по людям)."""
    sums: dict[str, list[float]] = {}
    for attempt in attempts:
        for band, (earned, possible) in _band_points(attempt).items():
            if possible:
                row = sums.setdefault(band, [0.0, 0.0, 0])
                row[0] += earned
                row[1] += possible
                row[2] += 1
    priors = dict(DEFAULT_BAND_PRIOR)
    for band, (earned, possible, n) in sums.items():
        if n >= BAND_PRIOR_MIN_CANDIDATES:
            priors[band] = earned / possible
    return priors


def band_rate(attempt: Attempt | None, level: str, priors: dict[str, float] | None = None) -> tuple[float, list]:
    if not attempt_summary(attempt):
        return 0.0, []
    priors = priors or DEFAULT_BAND_PRIOR
    points = _band_points(attempt)
    total = weight = 0.0
    detail = []
    for band, w in CATEGORY_BANDS[level]:
        earned, possible = points.get(band, (0, 0))
        rate = (earned + BAND_PRIOR_POINTS * priors[band]) / (possible + BAND_PRIOR_POINTS)
        total += w * rate
        weight += w
        detail.append(
            {
                "band": BAND_TITLES[band],
                "rate": round(earned / possible, 3) if possible else None,
                "points": [earned, possible],
                "smoothed": round(rate, 3),
                "category_average": round(priors[band], 3),
            }
        )
    return total / weight, detail


def load_facts(
    db: Session,
    specialization: str | None = None,
    levels: list[str] | None = None,
    user_ids: list[uuid.UUID] | None = None,
    only_published: bool = True,
    with_estimates: bool = True,
    include_unconfirmed: bool = True,
) -> list[Facts]:
    query = (
        select(CandidateGrade, User, CandidateProfile)
        .join(User, User.id == CandidateGrade.user_id)
        .join(CandidateProfile, CandidateProfile.user_id == User.id)
        .where(User.is_active.is_(True), User.role == "candidate")
    )
    if specialization:
        query = query.where(CandidateGrade.specialization == specialization)
    if levels:
        query = query.where(CandidateGrade.level.in_(levels))
    if user_ids is not None:
        query = query.where(CandidateGrade.user_id.in_(user_ids))
    rows = list(db.execute(query).all())
    if include_unconfirmed:
        rows += _claimed_rows(db, specialization, levels, user_ids, {(g.user_id, g.specialization) for g, _u, _p in rows})
    if only_published:
        allowed = _published(db, [g.user_id for g, _u, _p in rows])
        rows = [r for r in rows if r[0].user_id in allowed]
    if not rows:
        return []
    ids = [g.user_id for g, _u, _p in rows]
    attempt_ids = [g.defining_attempt_id for g, _u, _p in rows if g.defining_attempt_id]
    attempts = {
        a.id: a for a in db.scalars(select(Attempt).options(load_only(*ATTEMPT_FIELDS)).where(Attempt.id.in_(attempt_ids)))
    }
    counts = dict(
        db.execute(
            select(Attempt.user_id, func.count()).where(Attempt.user_id.in_(ids), Attempt.status == "finished").group_by(Attempt.user_id)
        ).all()
    )
    estimates: dict = {}
    # строки, а не ORM-объекты: тысячи оценок без накладных расходов ORM
    estimate_columns = list(CompetencyEstimate.__table__.columns)
    rows_estimates = db.execute(select(*estimate_columns).where(CompetencyEstimate.user_id.in_(ids))) if with_estimates else []
    for e in rows_estimates:
        estimates.setdefault((e.user_id, e.specialization), {})[e.competency] = e
    achievements: dict = {}
    for a in db.scalars(select(FspAchievement).where(FspAchievement.user_id.in_(ids))):
        achievements.setdefault(a.user_id, []).append(a)
    links = dict(db.execute(select(FspLink.user_id, FspLink.sport_rank).where(FspLink.user_id.in_(ids))).all())
    tasks: dict = {}
    for t in db.scalars(
        select(TaskAssignment).where(TaskAssignment.candidate_user_id.in_(ids), TaskAssignment.status.in_(("submitted", "reviewed")))
    ):
        quality = 1.0 if t.auto_correct else 0.0 if t.auto_correct is False else (t.employer_score or 3) / 5.0
        entry = tasks.setdefault(t.candidate_user_id, [0, 0.0, None])
        entry[0] += 1
        entry[1] += quality
        if t.submitted_at and (entry[2] is None or t.submitted_at > entry[2]):
            entry[2] = t.submitted_at
    population = _population(db, rows, attempts, only_published) if user_ids is not None else None
    result = []
    for grade, user, profile in rows:
        attempt = attempts.get(grade.defining_attempt_id)
        facts = Facts(
            user=user,
            profile=profile,
            grade=grade,
            attempt=attempt,
            attempts_count=counts.get(user.id, 0),
            estimates=estimates.get((user.id, grade.specialization), {}),
            achievements=achievements.get(user.id, []),
            fsp_linked=user.id in links,
            fsp_rank=links.get(user.id),
        )
        if user.id in tasks:
            n, q, last = tasks[user.id]
            facts.tasks_solved, facts.tasks_quality, facts.last_task_at = n, q / n, last
        facts.fsp = fsp_service.fsp_score(facts.achievements, grade.specialization)
        result.append(facts)
    if population is None:
        population = {}
        for f in result:
            if is_confirmed(f.grade):
                population.setdefault((f.grade.specialization, f.grade.level), []).append(f.attempt)
    _assign_band_rates(result, population)
    return result


def _claimed_rows(db: Session, specialization, levels, user_ids, existing: set) -> list:
    """Кандидаты с опросом по направлению, но без грейда в нём — с заявленным уровнем."""
    # сначала лёгкие строки опросов (у большинства кандидатов уже есть грейд),
    # профили и пользователи загружаются только для оставшихся
    query = select(Survey.user_id, Survey.specialization, Survey.self_level).order_by(Survey.created_at)
    if specialization:
        query = query.where(Survey.specialization == specialization)
    if user_ids is not None:
        query = query.where(Survey.user_id.in_(user_ids))
    claimed: dict = {}
    for uid, spec, level in db.execute(query):
        if (uid, spec) not in existing:
            claimed[(uid, spec)] = level
    if not claimed:
        return []
    ids = list({uid for uid, _s in claimed})
    people = {
        user.id: (user, profile)
        for user, profile in db.execute(
            select(User, CandidateProfile)
            .join(CandidateProfile, CandidateProfile.user_id == User.id)
            .where(User.id.in_(ids), User.is_active.is_(True), User.role == "candidate")
        )
    }
    latest = {key: (level, *people[key[0]]) for key, level in claimed.items() if key[0] in people}
    if not latest:
        return []
    tested = set(
        db.execute(
            select(Attempt.user_id, Attempt.specialization).where(Attempt.user_id.in_(ids), Attempt.status == "finished")
        ).all()
    )
    pending = set(
        db.execute(
            select(GradeRecommendation.user_id, GradeRecommendation.specialization).where(
                GradeRecommendation.user_id.in_(ids), GradeRecommendation.resolved_at.is_(None)
            )
        ).all()
    )
    rows = []
    for (uid, spec), (self_level, user, profile) in latest.items():
        if levels and self_level not in levels:
            continue
        status = "decision_pending" if (uid, spec) in pending else "not_confirmed" if (uid, spec) in tested else "not_tested"
        rows.append((ClaimedGrade(uid, spec, self_level, status), user, profile))
    return rows


def _population(db: Session, rows, attempts: dict, only_published: bool) -> dict:
    """
    Определяющие попытки всех кандидатов категорий из rows. Нужны, когда
    загружается часть кандидатов (карточка одного человека): среднее по
    полосам и перцентиль считаются по всей категории, а не по выборке.
    """
    categories = {(g.specialization, g.level) for g, _u, _p in rows if is_confirmed(g)}
    query = (
        select(CandidateGrade)
        .join(User, User.id == CandidateGrade.user_id)
        .where(User.is_active.is_(True), User.role == "candidate")
    )
    grades = [g for g in db.scalars(query) if (g.specialization, g.level) in categories]
    if only_published:
        allowed = _published(db, [g.user_id for g in grades])
        grades = [g for g in grades if g.user_id in allowed]
    missing = [g.defining_attempt_id for g in grades if g.defining_attempt_id and g.defining_attempt_id not in attempts]
    if missing:
        attempts = dict(attempts)
        attempts.update(
            {a.id: a for a in db.scalars(select(Attempt).options(load_only(*ATTEMPT_FIELDS)).where(Attempt.id.in_(missing)))}
        )
    population: dict = {}
    for g in grades:
        population.setdefault((g.specialization, g.level), []).append(attempts.get(g.defining_attempt_id))
    return population


def _assign_band_rates(facts: list[Facts], population: dict) -> None:
    """Сглаженная доля баллов по полосам уровня и место среди кандидатов категории."""
    priors = {key: band_priors(attempts) for key, attempts in population.items()}
    rates: dict = {}
    for (spec, level), attempts in population.items():
        rates[(spec, level)] = sorted(band_rate(a, level, priors[(spec, level)])[0] for a in attempts if a is not None)
    for f in facts:
        if not is_confirmed(f.grade):
            f.band_rate, f.band_detail, f.percentile = 0.0, [], 0.0
            continue
        key = (f.grade.specialization, f.grade.level)
        f.band_rate, f.band_detail = band_rate(f.attempt, f.grade.level, priors.get(key))
        values = rates.get(key) or []
        below = bisect_left(values, f.band_rate)
        equal = bisect_right(values, f.band_rate) - below
        f.percentile = (below + 0.5 * equal) / len(values) if len(values) > 1 else 0.5


# ------------------------------------------------------------------ факторы


def test_strength(f: Facts) -> tuple[float, str]:
    if not is_confirmed(f.grade):
        return 0.0, "Грейд не подтверждён: заявлен %s, %s" % (f.grade.level.capitalize(), CLAIM_STATUS_TITLES[f.grade.status])
    # смесь абсолютного результата и места в категории: при малом числе
    # кандидатов перцентиль неустойчив, при большом — точнее отражает силу
    value = 0.5 * f.band_rate + 0.5 * f.percentile
    level = f.grade.level
    notes = []
    if f.attempt is not None and f.attempt.declared_level != level:
        notes.append("подтверждено по тесту уровня %s" % f.attempt.declared_level.capitalize())
    absent = [d["band"] for d in f.band_detail if d["rate"] is None]
    if absent:
        notes.append("заданий %s в тесте не было — учтено среднее категории" % ", ".join(absent))
    text = "Задания уровня %s: оценка %d%% — сильнее, чем у %d%% кандидатов категории%s" % (
        level.capitalize(),
        round(f.band_rate * 100),
        round(f.percentile * 100),
        " (%s)" % "; ".join(notes) if notes else "",
    )
    return value, text


def freshness(f: Facts, now: datetime) -> tuple[float, str]:
    last = max([d for d in (f.attempt.finished_at if f.attempt else None, f.last_task_at, f.profile.last_active_at) if d],
               default=None)
    days = (now - last).days if last else 365
    recency = math.exp(-days / 180)
    tasks = min(1.0, f.tasks_solved / 3) * f.tasks_quality if f.tasks_solved else 0.0
    value = 0.6 * recency + 0.4 * tasks
    parts = ["активность %d дн. назад" % days]
    if f.tasks_solved:
        parts.append("решено заданий работодателей: %d" % f.tasks_solved)
    return value, ", ".join(parts)


def shows(profile, field: str) -> bool:
    """Поле видно работодателю по настройкам приватности кандидата."""
    return bool((getattr(profile, "privacy", None) or {}).get(field, True))


def visible_fsp_top(f: Facts) -> list:
    """Лучшие достижения ФСП, если кандидат их не скрыл."""
    return (f.fsp.get("top") or []) if shows(f.profile, "show_fsp") else []


def fsp_factor(f: Facts) -> tuple[float, str]:
    if not shows(f.profile, "show_fsp"):
        return 0.0, FSP_HIDDEN_TEXT
    if not f.fsp_linked:
        return 0.0, "ФСП ID не привязан — фактор не учитывается"
    if not f.fsp.get("top"):
        return 0.0, "ФСП ID привязан, достижений пока нет"
    top = f.fsp["top"][0]
    return f.fsp["score"], "%s: %s (%s, %s)" % (
        top["result_title"], top["event_name"], top["event_level_title"].lower(), top["event_date"][:4]
    )


def competency_fit(f: Facts, weights: dict[str, float]) -> tuple[float, list, list]:
    p0 = f.overall_rate
    num = den = 0.0
    measured = []
    unmeasured = []
    for comp, w in weights.items():
        est = f.estimates.get(comp)
        value = est.estimate if est else p0
        num += w * value
        den += w
        if est:
            measured.append((comp, w, est.estimate, est.confidence))
        elif w >= 0.6:
            unmeasured.append(comp)
    fit = num / den if den else p0
    strengths = sorted((m for m in measured if m[2] >= 0.7), key=lambda m: -(m[1] * m[2]))[:3]
    gaps = sorted((m for m in measured if m[2] < 0.5 and m[1] >= 0.6), key=lambda m: -m[1])[:2]
    return fit, strengths, gaps + [(c, weights[c], None, 0.0) for c in unmeasured[:2]]


def candidate_skills(f: Facts) -> set[str]:
    return {s for s in (f.profile.stack or []) if s in SKILLS}


def skill_confirmed(f: Facts, slug: str) -> bool:
    """Навык подкреплён тестом: связанная компетенция специализации измерена с оценкой от 50 %."""
    for comp in skill_competencies(slug, f.grade.specialization):
        est = f.estimates.get(comp)
        if est is not None and est.estimate >= SKILL_CONFIRMED_AT:
            return True
    return False


def stack_fit(f: Facts, need_skills: list[str]) -> tuple[float, list, list, list]:
    """
    Доля навыков потребности в заявленном стеке. Навык с подтверждённой
    тестом компетенцией весит 1, только заявленный — 0,5. Возвращает
    (значение, совпавшие, отсутствующие, подтверждённые тестом).
    """
    if not need_skills:
        return 0.5, [], [], []
    have = candidate_skills(f)
    matched = [s for s in need_skills if s in have]
    missing = [s for s in need_skills if s not in have]
    confirmed = [s for s in matched if skill_confirmed(f, s)]
    value = (len(confirmed) + UNCONFIRMED_SKILL * (len(matched) - len(confirmed))) / len(need_skills)
    return value, matched, missing, confirmed


def conditions(f: Facts, need) -> tuple[float, list[str], list[str], list[dict]]:
    """Снижение балла за несовпадение условий и пояснения к нему.

    Четвёртым значением возвращается разбор: из чего сложилось снижение и
    какая доля пришлась на каждую причину. Доли в сумме дают сам
    коэффициент (потолок 0.4 выше суммы всех трёх, поэтому не срезает).
    """
    penalty = 0.0
    notes, warnings, reasons = [], [], []
    expectation = f.profile.salary_expectation
    if expectation:
        if expectation > need.salary_to:
            penalty += PENALTY_SALARY
            text = "Ожидания %s ₽ выше вилки" % format(expectation, ",").replace(",", " ")
            warnings.append(text)
            reasons.append({"title": text, "share": PENALTY_SALARY})
        else:
            notes.append("Ожидания %s ₽ — в пределах вилки" % format(expectation, ",").replace(",", " "))
    else:
        # штрафа нет (это не несовпадение), но работодатель должен знать, что условия не сверены
        warnings.append("Ожидания по зарплате не указаны — уточните при контакте")
    formats = set(f.profile.work_formats or [])
    if need.work_format and need.work_format != "any" and formats and need.work_format not in formats:
        penalty += PENALTY_FORMAT
        text = "Предпочитает формат: " + ", ".join(WORK_FORMATS.get(x, x) for x in sorted(formats))
        warnings.append(text)
        reasons.append({"title": text, "share": PENALTY_FORMAT})
    if need.city and need.work_format in ("office", "hybrid") and not shows(f.profile, "show_city"):
        # город скрыт: считаем неизвестным, без штрафа и без намёка на то, какой он
        warnings.append("Город кандидат не показывает — уточните при контакте")
    elif need.city and need.work_format in ("office", "hybrid"):
        same_city = (f.profile.city or "").strip().lower() == need.city.strip().lower()
        if not same_city and not f.profile.relocation:
            penalty += PENALTY_CITY
            text = "Другой город, переезд не рассматривает"
            warnings.append(text)
            reasons.append({"title": text, "share": PENALTY_CITY})
    return min(penalty, 0.4), notes, warnings, reasons


# ------------------------------------------------------------------ ранжирование


def _factor(name: str, value: float, weight: float, text: str) -> dict:
    return {
        "factor": name,
        "title": FACTOR_TITLES[name],
        "value": round(value, 3),
        "weight": weight,
        "contribution": round(100 * value * weight, 1),
        "text": text,
    }


def score_for_category(f: Facts, now: datetime | None = None) -> dict:
    now = now or utcnow()
    t_value, t_text = test_strength(f)
    p_value, p_text = fsp_factor(f)
    r_value, r_text = freshness(f, now)
    factors = [
        _factor("test", t_value, CATEGORY_WEIGHTS["test"], t_text),
        _factor("fsp", p_value, CATEGORY_WEIGHTS["fsp"], p_text),
        _factor("freshness", r_value, CATEGORY_WEIGHTS["freshness"], r_text),
    ]
    score = sum(x["contribution"] for x in factors)
    return {"score": round(score, 1), "factors": factors, "highlights": [t_text] + ([p_text] if p_value else []), "warnings": []}


def score_for_need(f: Facts, need, profile: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    weights = profile["competency_weights"]
    c_value, strengths, gaps = competency_fit(f, weights)
    t_value, t_text = test_strength(f)
    s_value, matched, missing, confirmed = stack_fit(f, profile.get("skills") or [])
    p_value, p_text = fsp_factor(f)
    r_value, r_text = freshness(f, now)
    penalty, notes, warnings, penalty_reasons = conditions(f, need)

    if strengths:
        c_text = "Сильные стороны для задачи: " + ", ".join(
            "%s %d%%" % (COMPETENCY_TITLES.get(c, c), round(v * 100)) for c, _w, v, _conf in strengths
        )
    else:
        c_text = "Подтверждённых сильных сторон по ключевым компетенциям задачи нет"
    if matched:
        parts = []
        if confirmed:
            parts.append("подтверждено тестом — " + ", ".join(SKILLS[s][0] for s in confirmed))
        declared_only = [s for s in matched if s not in confirmed]
        if declared_only:
            parts.append("только заявлено — " + ", ".join(SKILLS[s][0] for s in declared_only))
        s_text = "Совпадает %d из %d: %s" % (len(matched), len(matched) + len(missing), "; ".join(parts))
    else:
        s_text = "Совпадений по стеку нет"
    factors = [
        _factor("competencies", c_value, NEED_WEIGHTS["competencies"], c_text),
        _factor("test", t_value, NEED_WEIGHTS["test"], t_text),
        _factor("stack", s_value, NEED_WEIGHTS["stack"], s_text),
        _factor("fsp", p_value, NEED_WEIGHTS["fsp"], p_text),
        _factor("freshness", r_value, NEED_WEIGHTS["freshness"], r_text),
    ]
    base = sum(x["contribution"] for x in factors)
    score = base * (1 - penalty)
    if not is_confirmed(f.grade):
        warnings.insert(0, "Грейд не подтверждён тестом — кандидат стоит ниже подтверждённых")
    if minors.is_minor(f.profile):
        warnings.insert(0, "Кандидату меньше 18 лет: подходят только предложения с лёгким трудом и сокращённым временем"
                        if getattr(need, "suitable_for_minors", False) else
                        "Кандидату меньше 18 лет: чтобы пригласить, отметьте предложение «подходит для несовершеннолетних (15–17 лет)» "
                        "(лёгкий труд, сокращённое время)")
    for comp, _w, value, _conf in gaps:
        if value is None:
            warnings.append("Не измерено тестом: %s" % COMPETENCY_TITLES.get(comp, comp))
        else:
            warnings.append("Слабее по компетенции «%s»: %d%%" % (COMPETENCY_TITLES.get(comp, comp), round(value * 100)))
    if missing:
        warnings.append("Нет в заявленном стеке: " + ", ".join(SKILLS[s][0] for s in missing[:4]))
    highlights = [c_text, t_text] + ([p_text] if p_value else []) + notes
    return {
        "score": round(score, 1),
        "base_score": round(base, 1),
        "penalty": round(penalty, 2),
        # сколько баллов стоила каждая причина: доля считается от базового
        # балла, чтобы в интерфейсе не пересчитывать проценты в баллы
        "penalty_reasons": [
            {"title": r["title"], "points": round(base * r["share"], 1)} for r in penalty_reasons
        ],
        "factors": factors,
        "highlights": highlights[:4],
        "warnings": warnings[:5],
    }


def target_levels(level: str) -> list[tuple[str, str]]:
    """Категории, из которых берутся кандидаты под потребность уровня level."""
    idx = LEVELS.index(level)
    result = [(level, "основная категория")]
    if idx + 1 < len(LEVELS):
        result.append((LEVELS[idx + 1], "с запасом квалификации"))
    if idx > 0:
        result.append((LEVELS[idx - 1], "на вырост"))
    return result


# Статистика категорий одинакова для всех работодателей и не содержит
# персональных данных: её пересчёт на каждый запрос — самая тяжёлая операция
# кабинета работодателя, поэтому она кэшируется в процессе на короткое время.
CATEGORY_STATS_TTL = 30.0
_category_cache: dict = {}
_category_lock = threading.Lock()


def category_stats(db: Session, specialization: str | None = None) -> list[dict]:
    now = time.monotonic()
    with _category_lock:
        cached = _category_cache.get(specialization)
        if cached and now - cached[0] < CATEGORY_STATS_TTL:
            return cached[1]
    rows = _category_stats(db, specialization)
    with _category_lock:
        _category_cache[specialization] = (now, rows)
    return rows


def reset_category_cache() -> None:
    with _category_lock:
        _category_cache.clear()


def _category_stats(db: Session, specialization: str | None = None) -> list[dict]:
    facts = load_facts(db, specialization=specialization, with_estimates=False)  # сила профиля без компетенций
    stats: dict = {}
    for f in facts:
        key = (f.grade.specialization, f.grade.level)
        entry = stats.setdefault(key, {"count": 0, "with_fsp": 0, "strength_sum": 0.0, "unconfirmed": 0})
        if not is_confirmed(f.grade):
            entry["unconfirmed"] += 1  # видны в категории отдельно, в среднюю силу не входят
            continue
        entry["count"] += 1
        entry["with_fsp"] += 1 if visible_fsp_top(f) else 0
        entry["strength_sum"] += score_for_category(f)["score"]
    rows = []
    for spec in SPECIALIZATIONS:
        if specialization and spec != specialization:
            continue
        for level in LEVELS:
            entry = stats.get((spec, level), {"count": 0, "with_fsp": 0, "strength_sum": 0.0, "unconfirmed": 0})
            rows.append(
                {
                    "specialization": spec,
                    "specialization_title": SPECIALIZATIONS[spec],
                    "level": level,
                    "title": "%s · %s" % (SPECIALIZATIONS[spec], level),
                    "candidates": entry["count"],
                    "unconfirmed": entry["unconfirmed"],
                    "with_fsp_achievements": entry["with_fsp"],
                    "avg_profile_strength": round(entry["strength_sum"] / entry["count"], 1) if entry["count"] else None,
                }
            )
    return rows


def level_order(level: str) -> int:
    return LEVEL_INDEX[level]


def sanitize_match(match: dict | None, profile) -> dict | None:
    """
    Сохранённое обоснование (подборка, приглашение) с учётом текущих
    настроек приватности: если кандидат скрыл достижения ФСП после того, как
    обоснование было построено, они убираются из текста.
    """
    if not match or shows(profile, "show_fsp"):
        return match
    match = dict(match)
    hidden = None
    factors = []
    for factor in match.get("factors") or []:
        if factor.get("factor") == "fsp":
            hidden = factor.get("text")
            factor = {**factor, "value": 0.0, "contribution": 0.0, "text": FSP_HIDDEN_TEXT}
        factors.append(factor)
    match["factors"] = factors
    if hidden:
        match["highlights"] = [h for h in match.get("highlights") or [] if h != hidden]
    return match
