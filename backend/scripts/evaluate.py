"""
Процедура валидации: категоризация, подбор и защита от «добора» грейда.

Синтетические кандидаты из scripts/seed_demo.py имеют скрытый истинный
профиль: модель вероятностей ответа по сложности (профили симулятора
банка), отклонения по компетенциям и настоящий стек. Платформа его не
видит: она получает только ответы на тест, заявленные данные и
достижения ФСП. Сравнение с истинным профилем показывает, насколько
хорошо платформа восстанавливает то, что нужно работодателю.

Истинная способность на уровне L – средняя вероятность решить задания
полос сложности уровня (junior d1-6, middle d4-8, senior d7-10) с учётом
отклонений по компетенциям. Жёсткой «правильной» границы уровней нет:
профили симулятора перекрываются (strong_junior решает задания middle
лучше, чем weak_middle, а strong_middle – задания senior лучше, чем
weak_senior). Поэтому категоризация проверяется без произвольных порогов:

1. Категоризация (тест против самооценки того же кандидата):
   * C-индекс – доля пар кандидатов одной специализации с разными
     уровнями, где у более высокого уровня выше и общая способность
     (d1-10); 0,5 – случайное упорядочивание, 1 – идеальное;
   * явно завышен – способность на присвоенном уровне не выше, чем у
     типичного кандидата уровнем ниже (solid_(L−1); для junior –
     угадывание);
   * явно занижен – способность на уровне выше присвоенного не ниже,
     чем у типичного кандидата того уровня (solid_(L+1));
   * без категории – кандидат не слабее типичного junior, но категории нет.

2. Подбор под потребность (6 демо-вакансий + 9 ролевых профилей).
   Истинная релевантность кандидата потребности уровня L:
       relevance = (0,8 · ability_L(веса компетенций потребности)
                    + 0,2 · доля навыков потребности в настоящем стеке) · условия
   где условия – 0,7 при ожиданиях выше вилки и 0,8 при несовпадении
   формата. Релевантные – верхние 20 % пула по relevance. Метрики на
   первых 10: P@10, nDCG@10, MRR и доля явно не дотягивающих до уровня
   (не сильнее типичного кандидата уровнем ниже).
   Сравниваются: подбор платформы, его варианты без ФСП и без порядка
   категорий, просмотр категории без ранжирования, поиск по резюме
   (заявленный стек, уровень и опыт) и случайный порядок.

3. Пересдачи: вероятность получить категорию угадыванием за год при
   разных правилах; исходы попыток берутся из настоящего банка.

4. Согласованность: вероятность, что две независимые попытки одного и
   того же кандидата (разные сиды – разные задания) дают один и тот же
   подтверждённый уровень: Σ pₖ² по распределению исходов.

Запуск (из каталога backend):
    python -m scripts.evaluate                 # по текущей базе
    python -m scripts.evaluate --runs 5        # 5 независимых наборов данных
    python -m scripts.evaluate --reuse-runs    # пересчитать разделы 3-4, взяв 1-2 из reports/evaluation.json
Отчёт: reports/evaluation_report.md и reports/evaluation.json.
"""

import argparse
import json
import logging
import math
import os
import random
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("junior", "middle", "senior")
BANDS = {"junior": range(1, 7), "middle": range(4, 9), "senior": range(7, 11)}
TYPICAL = {"junior": "solid_junior", "middle": "solid_middle", "senior": "solid_senior"}
LOWER_TYPICAL = {"junior": "guesser", "middle": "solid_junior", "senior": "solid_middle"}
ALL_BANDS = range(1, 11)
TYPICAL_YEARS = {"junior": 1.0, "middle": 3.5, "senior": 7.0}
ROLE_SALARY = {"junior": (80_000, 140_000), "middle": (180_000, 280_000), "senior": (300_000, 450_000)}
K = 10
RELEVANT_SHARE = 0.20
METHODS = {
    "platform": "Подбор платформы",
    "platform_no_fsp": "Платформа без фактора ФСП",
    "platform_score_only": "Платформа без порядка категорий",
    "category_browse": "Просмотр категории без ранжирования",
    "resume_keywords": "Поиск по резюме (заявленные стек, уровень, опыт)",
    "random": "Случайный порядок",
}


# ------------------------------------------------------------------ истинный профиль


def ability(probs: list[float], offsets: dict, level: str, weights: dict | None = None) -> float:
    """Средняя вероятность решить задания уровня; weights – веса компетенций (по умолчанию равные)."""
    comps = weights or dict.fromkeys(offsets, 1.0) or {"_": 1.0}
    num = den = 0.0
    for comp, w in comps.items():
        off = offsets.get(comp, 0.0)
        num += w * statistics.mean(min(0.99, max(0.02, probs[d - 1] + off)) for d in BANDS[level])
        den += w
    return num / den if den else 0.0


def overall_ability(probs: list[float], offsets: dict) -> float:
    comps = offsets or {"_": 0.0}
    return statistics.mean(
        statistics.mean(min(0.99, max(0.02, probs[d - 1] + off)) for d in ALL_BANDS) for off in comps.values()
    )


def reference_points(profiles: dict) -> dict:
    """Способность типичного кандидата уровня и уровня ниже – на заданиях уровня L."""
    return {
        lvl: {"typical": ability(profiles[TYPICAL[lvl]], {}, lvl), "lower": ability(profiles[LOWER_TYPICAL[lvl]], {}, lvl)}
        for lvl in LEVELS
    }


# ------------------------------------------------------------------ метрики


def precision_at(ranking, relevant, k=K):
    return sum(1 for c in ranking[:k] if c in relevant) / k


def ndcg_at(ranking, gains, k=K):
    dcg = sum(gains.get(c, 0.0) / math.log2(i + 2) for i, c in enumerate(ranking[:k]))
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def reciprocal_rank(ranking, relevant):
    for i, c in enumerate(ranking):
        if c in relevant:
            return 1.0 / (i + 1)
    return 0.0


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        r = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def c_index(rows: list[tuple[str, str, float]]) -> float | None:
    """rows: (специализация, уровень, способность). Пары с разными уровнями одной специализации."""
    concordant = ties = total = 0
    by_spec = defaultdict(list)
    for spec, level, value in rows:
        by_spec[spec].append((LEVELS.index(level), value))
    for items in by_spec.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (li, vi), (lj, vj) = items[i], items[j]
                if li == lj:
                    continue
                total += 1
                if vi == vj:
                    ties += 1
                elif (li > lj) == (vi > vj):
                    concordant += 1
    return (concordant + 0.5 * ties) / total if total else None


def mismatch(level: str, abilities: dict, refs: dict) -> tuple[bool, bool]:
    """(явно завышен, явно занижен) для уровня level при способностях abilities[уровень]."""
    over = abilities[level] <= refs[level]["lower"]
    idx = LEVELS.index(level)
    under = idx + 1 < len(LEVELS) and abilities[LEVELS[idx + 1]] >= refs[LEVELS[idx + 1]]["typical"]
    return over, under


def compare_levels(rows: list[dict], key: str, refs: dict) -> dict:
    graded = [r for r in rows if r[key] in LEVELS]
    flags = [mismatch(r[key], r["abilities"], refs) for r in graded]
    n = len(graded)
    return {
        "total": len(rows),
        "graded": n,
        "c_index": c_index([(r["spec"], r[key], r["overall"]) for r in graded]),
        "overstated": sum(1 for o, _u in flags if o) / n if n else None,
        "understated": sum(1 for _o, u in flags if u) / n if n else None,
        "missed": sum(1 for r in rows if r[key] not in LEVELS and r["abilities"]["junior"] >= refs["junior"]["typical"]) / len(rows),
    }


# ------------------------------------------------------------------ один набор данных


def evaluate_dataset() -> dict:
    """Оценка по базе из APP_DATA_DIR (заполненной scripts/seed_demo.py)."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.data.role_profiles import DEMO_VACANCIES, ROLE_PROFILES
    from app.db import SessionLocal
    from app.models import CandidateGrade, CandidateProfile, Need, User
    from app.services.bank import bank
    from app.services.consents import has_consent

    settings = get_settings()
    truth_path = settings.data_dir / "seed_truth.json"
    if not truth_path.exists():
        raise SystemExit("Нет %s – сначала python -m scripts.seed_demo --reset" % truth_path)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))["candidates"]
    profiles_model = bank().simulator().PROFILES
    refs = reference_points(profiles_model)
    db = SessionLocal()

    users = {u.public_id: u for u in db.scalars(select(User).where(User.public_id.in_(list(truth))))}
    profiles = {
        p.user_id: p
        for p in db.scalars(select(CandidateProfile).where(CandidateProfile.user_id.in_([u.id for u in users.values()])))
    }
    grades = {(g.user_id, g.specialization): g.level for g in db.scalars(select(CandidateGrade))}

    # ---------------------------------------------------------- 1. категоризация
    rows = []
    by_label = Counter()
    ability_by_category = defaultdict(list)
    for pid, t in truth.items():
        probs, offsets = profiles_model[t["profile_model"]], t["competency_offsets"]
        assigned = grades.get((users[pid].id, t["specialization"]), "–")
        row = {
            "spec": t["specialization"],
            "test": assigned,
            "self": t["declared_level"],
            "overall": overall_ability(probs, offsets),
            "abilities": {lvl: ability(probs, offsets, lvl) for lvl in LEVELS},
        }
        rows.append(row)
        by_label[(t["true_level"], assigned)] += 1
        ability_by_category[assigned].append(row["overall"])
    categorization = {
        "reference_points": refs,
        "test": compare_levels(rows, "test", refs),
        "self_declared": compare_levels(rows, "self", refs),
        "ability_by_category": {
            k: {"n": len(v), "mean": statistics.mean(v), "min": min(v), "max": max(v)} for k, v in ability_by_category.items()
        },
        "label_matrix": {f: {a: by_label[(f, a)] for a in LEVELS + ("–",)} for f in LEVELS},
    }

    # ---------------------------------------------------------- 2. подбор
    needs = []
    for v in DEMO_VACANCIES:
        fields = ("title", "specialization", "level", "description", "team_description", "stack", "work_format", "city",
                  "salary_from", "salary_to")
        needs.append(("vacancy", Need(**{k: v[k] for k in fields})))
    for (spec, level), data in ROLE_PROFILES.items():
        lo, hi = ROLE_SALARY[level]
        needs.append(("role_profile", Need(
            title=data["title"], specialization=spec, level=level, description=data["summary"],
            team_description=" ".join(data["responsibilities"]), stack=data["typical_stack"], work_format="any",
            city=None, salary_from=lo, salary_to=hi)))

    by_spec = defaultdict(list)
    for pid, t in truth.items():
        user = users[pid]
        if profiles[user.id].open_to_offers and has_consent(db, user.id, "profile_publication"):
            by_spec[t["specialization"]].append(pid)

    rng = random.Random(97)
    per_need = []
    need_sets = []
    ctx = {"truth": truth, "users": users, "profiles": profiles, "profiles_model": profiles_model, "refs": refs}
    for kind, need in needs:
        pool = by_spec[need.specialization]
        entry, relevant = evaluate_need(db, kind, need, pool, ctx, rng)
        per_need.append(entry)
        need_sets.append((need, relevant, pool))
    inflation = stack_inflation(db, need_sets, by_spec, truth, users, profiles)
    db.close()

    summary = {
        name: {m: statistics.mean(n["metrics"][name][m] for n in per_need) for m in ("p10", "ndcg10", "mrr", "below_bar")}
        for name in METHODS
    }
    rhos = [n["spearman_score_vs_truth"] for n in per_need if n["spearman_score_vs_truth"] is not None]
    return {
        "categorization": categorization,
        "matching": {"summary": summary, "needs": per_need, "spearman_mean": statistics.mean(rhos) if rhos else None,
                     "stack_inflation": inflation},
    }


def evaluate_need(db, kind: str, need, pool: list[str], ctx: dict, rng: random.Random) -> tuple[dict, set]:
    """
    Метрики подбора под одну потребность: истинная релевантность пула,
    рейтинги платформы и базовых методов, их P@10, nDCG@10, MRR и доля
    явно слабых в первой десятке. Возвращает (строку отчёта, релевантных).
    """
    from app.services import search
    from app.services.needs import build_need_profile

    truth, users, profiles = ctx["truth"], ctx["users"], ctx["profiles"]
    profiles_model, refs = ctx["profiles_model"], ctx["refs"]
    need.profile = build_need_profile(need.specialization, need.level, need.stack, need.description, need.team_description)
    weights = need.profile["competency_weights"]
    skills = need.profile.get("skills") or list(need.stack)

    def relevance(pid):
        t = truth[pid]
        a = ability(profiles_model[t["profile_model"]], t["competency_offsets"], need.level, weights)
        stack = len(set(skills) & set(t["true_stack"])) / len(skills) if skills else 0.5
        cond = 1.0
        if t["salary_expectation"] > need.salary_to:
            cond *= 0.7
        if need.work_format != "any" and need.work_format not in t["work_formats"]:
            cond *= 0.8
        return (0.8 * a + 0.2 * stack) * cond

    def below_bar(pid):
        t = truth[pid]
        return ability(profiles_model[t["profile_model"]], t["competency_offsets"], need.level) <= refs[need.level]["lower"]

    gains = {pid: relevance(pid) for pid in pool}
    cutoff = sorted(gains.values(), reverse=True)[max(0, int(len(pool) * RELEVANT_SHARE) - 1)]
    relevant = {pid for pid, g in gains.items() if g >= cutoff}

    def complete(ranked):
        seen = set(ranked)
        rest = [pid for pid in pool if pid not in seen]
        rng.shuffle(rest)
        return ranked + rest

    rows = search.rank_for_need(db, need, search.SearchFilters(limit=200))
    pid_of = {f.user.id: f.user.public_id for f, _m in rows}

    def main_first(row):
        return 0 if row[0].grade.level == need.level else 1

    def without_fsp(match):
        base = sum(x["contribution"] for x in match["factors"] if x["factor"] != "fsp")
        return base / (1 - 0.15) * (1 - match["penalty"])

    def resume_score(pid):
        t = truth[pid]
        stack = len(set(skills) & set(t["declared_stack"])) / len(skills) if skills else 0.0
        level = 1.0 if t["declared_level"] == need.level else 0.0
        years = profiles[users[pid].id].experience_years or 0.0
        exp = math.exp(-abs(years - TYPICAL_YEARS[need.level]) / 2)
        cond = 1.0
        if t["salary_expectation"] > need.salary_to:
            cond *= 0.85
        if need.work_format != "any" and need.work_format not in t["work_formats"]:
            cond *= 0.9
        return (0.5 * stack + 0.3 * level + 0.2 * exp) * cond

    browse = [pid_of[f.user.id] for f, _m in rows if f.grade.level == need.level]
    rng.shuffle(browse)
    rankings = {
        "platform": complete([pid_of[f.user.id] for f, _m in rows]),
        "platform_no_fsp": complete([pid_of[f.user.id] for f, _m in sorted(rows, key=lambda r: (main_first(r), -without_fsp(r[1])))]),
        "platform_score_only": complete([pid_of[f.user.id] for f, _m in sorted(rows, key=lambda r: -r[1]["score"])]),
        "category_browse": complete(browse),
        "resume_keywords": sorted(pool, key=lambda pid: -resume_score(pid)),
    }

    def measure(ranking):
        return {
            "p10": precision_at(ranking, relevant),
            "ndcg10": ndcg_at(ranking, gains),
            "mrr": reciprocal_rank(ranking, relevant),
            "below_bar": sum(1 for pid in ranking[:K] if below_bar(pid)) / K,
        }

    metrics = {name: measure(r) for name, r in rankings.items()}
    rand = defaultdict(list)
    for _ in range(200):
        ranking = list(pool)
        rng.shuffle(ranking)
        for k, v in measure(ranking).items():
            rand[k].append(v)
    metrics["random"] = {k: statistics.mean(v) for k, v in rand.items()}
    rho = spearman([m["score"] for _f, m in rows], [gains[pid_of[f.user.id]] for f, _m in rows])
    entry = {
        "kind": kind,
        "title": need.title,
        "specialization": need.specialization,
        "level": need.level,
        "pool": len(pool),
        "ranked_by_platform": len(rows),
        "main_category": sum(1 for f, _m in rows if f.grade.level == need.level),
        "relevant": len(relevant),
        "spearman_score_vs_truth": rho,
        "metrics": metrics,
    }
    return entry, relevant


INFLATED_SHARE = 0.2


def stack_inflation(db, need_sets, by_spec, truth, users, profiles) -> dict:
    """
    Устойчивость к накрутке стека: 20 % кандидатов каждого направления
    отмечают в профиле все навыки направления. Сравниваются два правила
    засчитывания навыков: «заявлен – значит засчитан» (как было) и
    правило платформы (без подтверждения тестом навык весит половину).
    Изменения делаются в текущей сессии и откатываются: база не меняется.
    """
    from app.reference import SKILLS
    from app.services import matching, search

    rng = random.Random(4545)
    inflated = set()
    for spec, pool in by_spec.items():
        everything = [slug for slug, (_t, _a, mapping) in SKILLS.items() if spec in mapping]
        for pid in rng.sample(pool, max(1, int(len(pool) * INFLATED_SHARE))):
            inflated.add(pid)
            profiles[users[pid].id].stack = list(everything)
    db.flush()
    result = {}
    original = matching.UNCONFIRMED_SKILL
    try:
        for name, weight in (("declared_counts", 1.0), ("platform", original)):
            matching.UNCONFIRMED_SKILL = weight
            shares, p10s = [], []
            for need, relevant, _pool in need_sets:
                rows = search.rank_for_need(db, need, search.SearchFilters(limit=200))
                top = [f.user.public_id for f, _m in rows][:K]
                if not top:
                    continue
                shares.append(sum(1 for pid in top if pid in inflated) / len(top))
                p10s.append(precision_at(top, relevant))
            result[name] = {"inflated_in_top10": statistics.mean(shares), "p10": statistics.mean(p10s)}
    finally:
        matching.UNCONFIRMED_SKILL = original
        db.rollback()
    result["inflated_share_in_pool"] = INFLATED_SHARE
    return result


# ------------------------------------------------------------------ 3. пересдачи


def outcome_samples(profile_name: str, per_cell: int, seed: int) -> dict:
    """Исходы попыток профиля по уровням теста (настоящая сборка и проверка банка)."""
    from app.services.bank import bank

    b = bank()
    sim = b.simulator()
    rng = random.Random(seed)
    samples = {}
    for spec in b.pools:
        for level in LEVELS:
            out = []
            for _ in range(per_cell):
                s = rng.getrandbits(63)
                test = b.assemble(spec, level, s)
                doc = b.result_document("x", test, sim.answer_as(profile_name, test, s ^ 0x5EED), "2026-10-06T00:00:00Z")
                out.append(doc["confirmed_level"])
            samples[(spec, level)] = out
    return samples


def level_open(policy: str, lvl: str, day: int, last: dict, last_failure: tuple | None) -> bool:
    """Доступен ли тест уровня lvl в день day по правилам policy (см. simulate_year)."""
    if policy == "none":
        return True
    if lvl in last and day - last[lvl] < 30:
        return False
    if (policy == "platform" and last_failure and day - last_failure[0] < 30
            and LEVELS.index(lvl) >= LEVELS.index(last_failure[1])):
        return False
    return True


def simulate_year(samples, spec, policy, rng, target=LEVELS, days=365, patient=False):
    """
    Кандидат без грейда пробует тест с лучшими шансами, как только правила
    позволяют. Возвращает уровень, полученный за год, или None.
    policy: none – без ограничений (одна попытка в день);
            retry30 – повтор того же уровня через 30 дней, рекомендации всегда;
            platform – retry30 + без рекомендаций после неудачи за 180 дней
                       + после неудачи сразу доступны только уровни ниже.
    patient – стратегия против правила 180 дней: пробовать только тогда,
    когда за 180 дней не было неудач, чтобы рекомендация оставалась доступной.
    """
    last = {}
    failures = []
    last_failure = None  # (день, уровень) последней неудачи — правило «после неудачи только ниже»
    for day in range(days):
        if patient and any(day - d < 180 for d in failures):
            continue
        level = next(
            (lvl for lvl in ("senior", "middle", "junior") if level_open(policy, lvl, day, last, last_failure)), None
        )
        if level is None:
            continue
        last[level] = day
        evidence = rng.choice(samples[(spec, level)])
        if evidence != "below_junior" and LEVELS.index(evidence) >= LEVELS.index(level):
            return evidence if evidence in target else None
        if evidence != "below_junior":
            clean = not any(day - d < 180 for d in failures)
            if (policy != "platform" or clean) and evidence in target:
                return evidence
        failures.append(day)
        last_failure = (day, level)
    return None


CONSISTENCY_CASES = (
    ("solid_junior", "junior"), ("strong_junior", "junior"),
    ("weak_middle", "middle"), ("solid_middle", "middle"), ("strong_middle", "middle"),
    ("weak_senior", "senior"), ("solid_senior", "senior"),
    ("solid_middle", "senior"), ("solid_junior", "middle"),
)


def evaluate_consistency(per_cell: int, seed: int) -> list[dict]:
    """Повторное прохождение: распределение исходов и вероятность совпадения двух попыток."""
    from app.services.bank import bank

    b = bank()
    sim = b.simulator()
    rng = random.Random(seed)
    rows = []
    for profile_name, level in CONSISTENCY_CASES:
        agree, dominant, counts_all = [], [], Counter()
        for spec in sorted(b.pools):
            counts = Counter()
            for _ in range(per_cell):
                s = rng.getrandbits(63)
                test = b.assemble(spec, level, s)
                doc = b.result_document("x", test, sim.answer_as(profile_name, test, s ^ 0xC0DE), "2026-10-06T00:00:00Z")
                counts[doc["confirmed_level"]] += 1
            shares = [n / per_cell for n in counts.values()]
            agree.append(sum(p * p for p in shares))
            dominant.append(max(shares))
            counts_all.update(counts)
        total = sum(counts_all.values())
        rows.append(
            {
                "profile": profile_name,
                "test_level": level,
                "distribution": {k: counts_all[k] / total for k in ("below_junior",) + LEVELS if counts_all[k]},
                "same_result_twice": statistics.mean(agree),
                "same_result_twice_min": min(agree),
                "dominant_share": statistics.mean(dominant),
            }
        )
    return rows


def evaluate_retakes(per_cell: int, years: int, seed: int) -> dict:
    rng = random.Random(seed)
    result = {}
    for profile_name, target, title in (
        ("guesser", LEVELS, "Угадывание: любая категория"),
        ("weak_junior", ("middle", "senior"), "Слабый junior: категория middle и выше"),
    ):
        samples = outcome_samples(profile_name, per_cell, seed)
        per_attempt = {"%s/%s" % key: sum(1 for x in v if x in target) / len(v) for key, v in samples.items()}
        policies = {}
        for name, policy, patient in (
            ("none", "none", False),
            ("retry30", "retry30", False),
            ("platform", "platform", False),
            ("platform_patient", "platform", True),
        ):
            hits = total = 0
            for spec in sorted({s for s, _l in samples}):
                for _ in range(years):
                    total += 1
                    hits += simulate_year(samples, spec, policy, rng, target, patient=patient) is not None
            policies[name] = hits / total
        result[profile_name] = {"title": title, "per_attempt": per_attempt, "per_year": policies}
    return result


# ------------------------------------------------------------------ отчёт


def pct(x):
    return "–" if x is None else "%.1f %%" % (100 * x)


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def cell(values, as_pct=True, many=False):
    m, sd = mean_sd(values)
    if m is None:
        return "–"
    if as_pct:
        return "%.1f %%" % (100 * m) + (" ± %.1f" % (100 * sd) if many else "")
    return "%.3f" % m + (" ± %.3f" % sd if many else "")


def write_report(runs: list[dict], retakes: dict, consistency: list[dict], meta: dict) -> str:
    many = len(runs) > 1
    refs = runs[0]["categorization"]["reference_points"]
    lines = [
        "# Отчёт валидации платформы",
        "",
        "Сформирован `scripts/evaluate.py`. Наборов данных: %d (сиды %s), кандидатов в наборе: %d. "
        % (len(runs), ", ".join(str(s) for s in meta["seeds"]), meta["candidates"])
        + ("Значения – среднее ± стандартное отклонение по наборам." if many else ""),
        "",
        "## 1. Категоризация",
        "",
        "Категория по тесту и правилам платформы против самооценки того же кандидата. Опорные точки – доля "
        "решаемых заданий уровня у типичного кандидата уровня и уровнем ниже: "
        + ", ".join("%s %.2f / %.2f" % (lvl, refs[lvl]["typical"], refs[lvl]["lower"]) for lvl in LEVELS) + ".",
        "",
        "| Источник | С категорией | C-индекс (упорядочивание по силе) | Явно завышен | Явно занижен | Достоин категории, но без неё |",
        "|---|---|---|---|---|---|",
    ]
    for key, title in (("test", "Тест платформы"), ("self_declared", "Самооценка кандидата")):
        rows = [r["categorization"][key] for r in runs]
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            title,
            cell([r["graded"] / r["total"] for r in rows], many=many),
            cell([r["c_index"] for r in rows], as_pct=False, many=many),
            cell([r["overstated"] for r in rows], many=many),
            cell([r["understated"] for r in rows], many=many),
            cell([r["missed"] for r in rows], many=many) if key == "test" else "–",
        ))
    abc = runs[0]["categorization"]["ability_by_category"]
    lines += [
        "",
        "Общая способность (доля решаемых заданий d1-10) по категориям первого набора:",
        "",
        "| Категория | Кандидатов | Среднее | Мин | Макс |",
        "|---|---|---|---|---|",
    ]
    for k in LEVELS + ("–",):
        if k in abc:
            lines.append("| %s | %d | %.2f | %.2f | %.2f |" % ("без категории" if k == "–" else k, abc[k]["n"], abc[k]["mean"], abc[k]["min"], abc[k]["max"]))
    lm = runs[0]["categorization"]["label_matrix"]
    lines += [
        "",
        "Справочно – метки генератора × категория (метки грубые: профили соседних уровней перекрываются):",
        "",
        "| метка \\ категория | junior | middle | senior | без категории |",
        "|---|---|---|---|---|",
    ]
    for f in LEVELS:
        lines.append("| %s | %s |" % (f, " | ".join(str(lm[f][a]) for a in LEVELS + ("–",))))
    lines += [
        "",
        "## 2. Подбор под потребность",
        "",
        "15 потребностей (6 демо-вакансий и 9 ролевых профилей). Релевантные – верхние 20 %% пула по истинной "
        "релевантности; K = %d. «Не дотягивает» – доля топ-10 не сильнее типичного кандидата уровнем ниже." % K,
        "",
        "| Метод | P@10 | nDCG@10 | MRR | Не дотягивает в топ-10 |",
        "|---|---|---|---|---|",
    ]
    for name, title in METHODS.items():
        s = [r["matching"]["summary"][name] for r in runs]
        lines.append("| %s | %s | %s | %s | %s |" % (
            title,
            cell([x["p10"] for x in s], as_pct=False, many=many),
            cell([x["ndcg10"] for x in s], as_pct=False, many=many),
            cell([x["mrr"] for x in s], as_pct=False, many=many),
            cell([x["below_bar"] for x in s], many=many),
        ))
    lines += [
        "",
        "Ранговая корреляция Спирмена между баллом соответствия и истинной релевантностью среди ранжированных "
        "кандидатов: %s." % cell([r["matching"]["spearman_mean"] for r in runs], as_pct=False, many=many),
        "",
        "По потребностям (первый набор):",
        "",
        "| Потребность | Категория | Пул | В основной категории | P@10 платформа / резюме | nDCG@10 платформа / резюме | Не дотягивает: платформа / резюме |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in runs[0]["matching"]["needs"]:
        p, r = n["metrics"]["platform"], n["metrics"]["resume_keywords"]
        lines.append("| %s | %s %s | %d | %d | %.1f / %.1f | %.3f / %.3f | %s / %s |" % (
            n["title"], n["specialization"], n["level"], n["pool"], n["main_category"],
            p["p10"], r["p10"], p["ndcg10"], r["ndcg10"], pct(p["below_bar"]), pct(r["below_bar"])))
    if all("stack_inflation" in r["matching"] for r in runs):
        lines += [
            "",
            "### 2а. Устойчивость к накрутке стека",
            "",
            "В каждом наборе 20 % кандидатов направления отмечают в профиле все навыки направления. Чем меньше их "
            "доля в топ-10 и чем выше P@10 (истинная релевантность считается по настоящему, а не заявленному стеку), "
            "тем устойчивее подбор к приукрашиванию.",
            "",
            "| Правило засчитывания навыков | Доля «накрутивших» в топ-10 (в пуле 20 %) | P@10 |",
            "|---|---|---|",
        ]
        for name, title in (("declared_counts", "Заявлен – значит засчитан"),
                            ("platform", "Платформа: без подтверждения тестом – половина веса")):
            s = [r["matching"]["stack_inflation"][name] for r in runs]
            lines.append("| %s | %s | %s |" % (
                title, cell([x["inflated_in_top10"] for x in s], many=many),
                cell([x["p10"] for x in s], as_pct=False, many=many)))
    lines += [
        "",
        "## 3. Пересдачи и «добор» грейда",
        "",
        "Кандидат без грейда весь год пробует тест с лучшими шансами, как только правила позволяют. Исходы попыток – "
        "из настоящей сборки и проверки банка (%d попыток на ячейку специализация × уровень), %d симулированных "
        "кандидато-лет на специализацию." % (meta["retake_per_cell"], meta["retake_years"]),
        "",
        "| Профиль | Без ограничений (попытка в день) | Повтор уровня через 30 дней | Правила платформы | Правила платформы, выжидание 180 дней |",
        "|---|---|---|---|---|",
    ]
    for data in retakes.values():
        y = data["per_year"]
        lines.append("| %s | %s | %s | %s | %s |" % (
            data["title"], pct(y["none"]), pct(y["retry30"]), pct(y["platform"]), pct(y["platform_patient"])))
    lines += ["", "Вероятность за одну попытку (тест специализация/уровень, ненулевые ячейки):", ""]
    for data in retakes.values():
        nonzero = sorted((k, v) for k, v in data["per_attempt"].items() if v > 0)
        lines.append("* %s: %s" % (data["title"], ", ".join("%s – %.1f %%" % (k, 100 * v) for k, v in nonzero) or "0 во всех ячейках"))
    lines += [
        "",
        "## 4. Согласованность при повторном прохождении",
        "",
        "Один и тот же кандидат проходит тест дважды с разными сидами (разные задания, варианты и порядок ответов). "
        "«Тот же результат дважды» – вероятность, что обе попытки дают один подтверждённый уровень (Σ pₖ², среднее "
        "по специализациям; в скобках – минимум). %d попыток на специализацию." % meta["consistency_per_cell"],
        "",
        "| Профиль кандидата | Тест | Распределение исходов | Доминирующий исход | Тот же результат дважды |",
        "|---|---|---|---|---|",
    ]
    for row in consistency:
        dist = ", ".join("%s %.0f %%" % (k, 100 * v) for k, v in row["distribution"].items())
        lines.append("| %s | %s | %s | %s | %s (%s) |" % (
            row["profile"], row["test_level"], dist, pct(row["dominant_share"]),
            pct(row["same_result_twice"]), pct(row["same_result_twice_min"])))
    lines += [
        "",
        "Типичные профили своего уровня (solid) получают один и тот же результат в большинстве повторов. Пограничные "
        "профили (weak_middle, weak_senior, strong_junior) делятся между соседними уровнями – для них это ожидаемо: "
        "по способности они лежат между уровнями. Повтор ограничен правилами платформы, а принятый грейд не "
        "понижается принудительно, поэтому разброс пограничных случаев не превращается в «скачущую» категорию.",
        "",
        "## Допущения и ограничения",
        "",
        "* Данные синтетические. Реальная валидация требует данных пилота: доли принятых приглашений, "
        "оценок работодателей после собеседований и повторных тестов.",
        "* Достижения ФСП в модели чаще и выше у сильных участников. Если в реальных данных связь слабее, "
        "вклад фактора ФСП будет меньше (строка «без фактора ФСП» показывает выдачу без него).",
        "* Истинная релевантность и балл платформы используют разные данные: платформа видит ответы на тест, "
        "заявленный стек (с пропусками и приукрашиванием) и ФСП, но не скрытый профиль.",
        "* Поиск по резюме – упрощённая модель «классической» площадки: заявленный стек, самооценка уровня и опыт.",
        "* Самооценка в модели: 60 % кандидатов называют свой уровень по метке, 25 % завышают на шаг, 15 % занижают.",
        "",
    ]
    return "\n".join(lines)


def run_child(seed: int, per_spec: int, data_dir: Path) -> dict:
    env = dict(os.environ, APP_DATA_DIR=str(data_dir), PYTHONIOENCODING="utf-8")
    subprocess.run(
        [sys.executable, "-m", "scripts.seed_demo", "--reset", "--seed", str(seed), "--per-spec", str(per_spec),
         "--no-showcase"],
        cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    out = data_dir / "evaluation_part.json"
    subprocess.run([sys.executable, "-m", "scripts.evaluate", "--dataset-only", str(out)], cwd=ROOT, env=env, check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Валидация категоризации и подбора")
    parser.add_argument("--runs", type=int, default=0, help="число независимых наборов данных (0 – текущая база)")
    parser.add_argument("--per-spec", type=int, default=80, help="кандидатов на специализацию в каждом наборе")
    parser.add_argument("--first-seed", type=int, default=2026)
    parser.add_argument("--retake-per-cell", type=int, default=400, help="попыток банка на ячейку для раздела 3")
    parser.add_argument("--retake-years", type=int, default=2000, help="симулированных кандидато-лет на специализацию")
    parser.add_argument("--consistency-per-cell", type=int, default=300, help="попыток на специализацию для раздела 4")
    parser.add_argument("--reuse-runs", action="store_true", help="взять разделы 1-2 из reports/evaluation.json")
    parser.add_argument("--dataset-only", help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.disable(logging.INFO)

    if args.dataset_only:
        Path(args.dataset_only).write_text(json.dumps(evaluate_dataset(), ensure_ascii=False), encoding="utf-8")
        return
    if args.reuse_runs:
        previous = json.loads((ROOT / "reports" / "evaluation.json").read_text(encoding="utf-8"))
        runs, seeds, candidates = previous["runs"], previous["meta"]["seeds"], previous["meta"]["candidates"]
    elif args.runs:
        seeds = [args.first_seed + i for i in range(args.runs)]
        runs = []
        with tempfile.TemporaryDirectory(prefix="fsp-eval-") as tmp:
            for s in seeds:
                print("набор данных, сид %d…" % s, flush=True)
                runs.append(run_child(s, args.per_spec, Path(tmp) / str(s)))
        candidates = args.per_spec * 3
    else:
        from app.config import get_settings

        truth = json.loads((get_settings().data_dir / "seed_truth.json").read_text(encoding="utf-8"))
        seeds = [truth["seed"]]
        runs = [evaluate_dataset()]
        candidates = len(truth["candidates"])
    print("пересдачи…", flush=True)
    retakes = evaluate_retakes(args.retake_per_cell, args.retake_years, 4242)
    print("согласованность…", flush=True)
    consistency = evaluate_consistency(args.consistency_per_cell, 4343)
    meta = {"seeds": seeds, "candidates": candidates, "retake_per_cell": args.retake_per_cell,
            "retake_years": args.retake_years, "consistency_per_cell": args.consistency_per_cell}
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "evaluation_report.md").write_text(write_report(runs, retakes, consistency, meta), encoding="utf-8", newline="\n")
    (reports / "evaluation.json").write_text(
        json.dumps({"meta": meta, "runs": runs, "retakes": retakes, "consistency": consistency}, ensure_ascii=False, indent=1),
        encoding="utf-8",
        newline="\n",
    )
    print("Отчёт: reports/evaluation_report.md")


if __name__ == "__main__":
    main()
