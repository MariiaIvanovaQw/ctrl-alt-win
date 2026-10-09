"""
Определение подтверждённого грейда по результату попытки.

Эталонная реализация docs/specification.md, раздел 5. Пороги лежат в
blueprint.GRADE_RULES и заданы отдельно для каждого заявленного уровня,
потому что у каждого уровня свой план сборки и, значит, своя сложность
теста: 70 баллов на junior-тесте и 70 баллов на senior-тесте — разные
достижения, сравнивать их по одному порогу нельзя.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blueprint import (
    COMPETENCY_MIN_POINTS,
    CRITICAL,
    GRADE_RULES,
    KEY,
    LEVEL_ORDER,
    MAX_PROMOTION_STEPS,
)


def competency_stats(result, names):
    """
    Баллы по перечисленным компетенциям, пригодные для вывода.

    Учитываются только компетенции, по которым в попытке набралось не менее
    COMPETENCY_MIN_POINTS возможных баллов: по одному заданию делать вывод
    о компетенции нельзя — результат слишком шумный.
    """
    scores = []
    for name in names:
        data = result["competencies"].get(name)
        if not data:
            continue
        if data["points_possible"] >= COMPETENCY_MIN_POINTS:
            scores.append(data["score"])
    return scores


def evaluate_rule(rule, metrics, key_scores, critical_scores):
    """Проверяет один набор условий, возвращает список результатов проверок."""
    checks = []

    def add(name, passed, detail):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    if "chance_margin_min" in rule:
        margin = metrics["overall"] - metrics["chance_baseline"]
        add(
            "chance_margin_min",
            margin >= rule["chance_margin_min"],
            "превышение случайного уровня %d при требуемом %d (базовый уровень %d)"
            % (margin, rule["chance_margin_min"], metrics["chance_baseline"]),
        )

    if "overall_min" in rule:
        add(
            "overall_min",
            metrics["overall"] >= rule["overall_min"],
            "%d >= %d" % (metrics["overall"], rule["overall_min"]),
        )

    for name, metric in (
        ("easy_rate_min", "easy_rate"),
        ("mid_rate_min", "mid_rate"),
        ("mid_plus_rate_min", "mid_plus_rate"),
        ("hard_rate_min", "hard_rate"),
        ("top_rate_min", "top_rate"),
    ):
        if name not in rule:
            continue
        value = metrics[metric]
        if value is None:
            add(name, True, "заданий этой полосы сложности в попытке не было")
        else:
            add(name, value >= rule[name], "%.3f >= %.2f" % (value, rule[name]))

    for name, metric in (
        ("mid_plus_solved_min", "mid_plus_solved"),
        ("hard_solved_min", "hard_solved"),
    ):
        if name in rule:
            add(name, metrics[metric] >= rule[name], "%d >= %d" % (metrics[metric], rule[name]))

    if "key_floor" in rule:
        floor = rule["key_floor"]
        allowed = rule.get("key_below_allowed", 0)
        below = [score for score in key_scores if score < floor]
        add(
            "key_competencies",
            len(below) <= allowed,
            "ниже порога %d: %d из %d учтённых, допустимо %d"
            % (floor, len(below), len(key_scores), allowed),
        )

    if "critical_covered_min" in rule:
        add(
            "critical_covered_min",
            len(critical_scores) >= rule["critical_covered_min"],
            "%d >= %d" % (len(critical_scores), rule["critical_covered_min"]),
        )

    if "critical_avg_min" in rule:
        average = sum(critical_scores) / float(len(critical_scores)) if critical_scores else 0.0
        add(
            "critical_avg_min",
            bool(critical_scores) and average >= rule["critical_avg_min"],
            "%.1f >= %d" % (average, rule["critical_avg_min"]),
        )

    return checks


def determine_grade(result, specialization, declared_level):
    """
    Возвращает подтверждённый грейд и полное обоснование решения.

    Наборы условий берутся по заявленному уровню. Проверка идёт от высшего
    доступного уровня к низшему; берётся первый, все условия которого
    выполнены. Если не выполнен ни один — below_junior. Результат
    дополнительно ограничен заявленным уровнем плюс MAX_PROMOTION_STEPS.
    """
    buckets = result["difficulty_buckets"]

    mid_plus_possible = sum(buckets[b]["points_possible"] for b in ("mid", "hard", "top"))
    mid_plus_earned = sum(buckets[b]["points_earned"] for b in ("mid", "hard", "top"))
    mid_plus_solved = sum(buckets[b]["correct"] for b in ("mid", "hard", "top"))
    hard_possible = sum(buckets[b]["points_possible"] for b in ("hard", "top"))
    hard_earned = sum(buckets[b]["points_earned"] for b in ("hard", "top"))
    hard_solved = sum(buckets[b]["correct"] for b in ("hard", "top"))

    metrics = {
        "overall": result["score"],
        "chance_baseline": result.get("chance_baseline", 0),
        "easy_rate": buckets["easy"]["rate"],
        "mid_rate": buckets["mid"]["rate"],
        "top_rate": buckets["top"]["rate"],
        "mid_plus_points_possible": mid_plus_possible,
        "mid_plus_rate": (mid_plus_earned / float(mid_plus_possible)) if mid_plus_possible else None,
        "mid_plus_solved": mid_plus_solved,
        "hard_points_possible": hard_possible,
        "hard_rate": (hard_earned / float(hard_possible)) if hard_possible else None,
        "hard_solved": hard_solved,
    }

    key_scores = competency_stats(result, KEY[specialization])
    critical_scores = competency_stats(result, CRITICAL[specialization])

    rules = GRADE_RULES[declared_level]
    checks = {}
    satisfied = "below_junior"
    for target in ("senior", "middle", "junior"):
        if target not in rules:
            continue
        checks[target] = evaluate_rule(rules[target], metrics, key_scores, critical_scores)
        if satisfied == "below_junior" and all(c["passed"] for c in checks[target]):
            satisfied = target

    declared_index = LEVEL_ORDER.index(declared_level)
    cap_index = min(declared_index + MAX_PROMOTION_STEPS, LEVEL_ORDER.index("senior"))
    satisfied_index = LEVEL_ORDER.index(satisfied)
    confirmed_index = min(satisfied_index, cap_index)
    confirmed = LEVEL_ORDER[confirmed_index]

    if confirmed_index > declared_index:
        outcome = "promoted"
    elif confirmed_index == declared_index:
        outcome = "confirmed"
    else:
        outcome = "downgraded"

    return {
        "confirmed_level": confirmed,
        "level_satisfied_by_rules": satisfied,
        "levels_available_for_declared": sorted(rules.keys()),
        "capped_by_declared_level": satisfied_index > cap_index,
        "outcome": outcome,
        "grade_confidence": "low" if len(key_scores) < 3 else "normal",
        "metrics": {
            "overall": metrics["overall"],
            "chance_baseline": metrics["chance_baseline"],
            "overall_above_chance": metrics["overall"] - metrics["chance_baseline"],
            "easy_rate": metrics["easy_rate"],
            "mid_rate": metrics["mid_rate"],
            "mid_plus_rate": None
            if metrics["mid_plus_rate"] is None
            else round(metrics["mid_plus_rate"], 4),
            "mid_plus_solved": mid_plus_solved,
            "mid_plus_points_possible": mid_plus_possible,
            "hard_rate": None if metrics["hard_rate"] is None else round(metrics["hard_rate"], 4),
            "hard_solved": hard_solved,
            "hard_points_possible": hard_possible,
            "top_rate": metrics["top_rate"],
            "key_competency_scores": sorted(key_scores),
            "key_competencies_counted": len(key_scores),
            "critical_competency_scores": sorted(critical_scores),
            "critical_competencies_counted": len(critical_scores),
        },
        "checks": checks,
    }
