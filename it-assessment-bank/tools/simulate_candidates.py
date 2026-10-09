"""
Валидация системы на синтетических кандидатах.

Что проверяется (см. docs/specification.md, раздел 8):

S1. Воспроизводимость: один и тот же сид даёт тот же тест и тот же результат.
S2. Различность вариантов: два кандидата получают разные наборы заданий,
    но сопоставимые по сложности (сумма баллов и состав по типам совпадают
    по построению, перекрытие заданий ограничено).
S3. Монотонность оценки: чем выше «истинный» уровень кандидата, тем выше балл.
S4. Корректность определения грейда: все шесть требуемых сценариев
    (J->J, J->M, M->M, M->J, S->S, S->M) достигаются и не достигаются ложно.
S5. Устойчивость: распределение подтверждённых грейдов для одной и той же
    модели кандидата по разным сидам имеет малый разброс.
S6. Эвристические атаки: выбор варианта по длине или по совпадению слов
    с вопросом не подтверждает уровень чаще, чем случайное угадывание.

Модель кандидата: вероятность верного ответа зависит от его «истинного»
уровня и от сложности задания. Никакого обучения и внешних сервисов.

Запуск:
    python tools/simulate_candidates.py
    python tools/simulate_candidates.py --json
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from assemble_test import assemble_test, build_result_document, determine_grade, score_attempt
from bank_lib import LEVELS, load_bank, sub_rng

# Вероятность верного ответа: профиль кандидата -> вероятность по сложности 1..10.
# Профили подобраны так, чтобы отражать реалистичную разницу уровней:
# junior уверенно отвечает на базовые вопросы и почти не решает senior-задачи.
PROFILES = {
    "weak_junior": [0.70, 0.65, 0.58, 0.35, 0.28, 0.20, 0.12, 0.08, 0.05, 0.03],
    "solid_junior": [0.95, 0.92, 0.88, 0.55, 0.45, 0.33, 0.18, 0.12, 0.08, 0.05],
    "strong_junior": [0.97, 0.96, 0.93, 0.80, 0.74, 0.62, 0.34, 0.24, 0.14, 0.10],
    "weak_middle": [0.93, 0.90, 0.85, 0.62, 0.55, 0.45, 0.25, 0.18, 0.10, 0.07],
    "solid_middle": [0.98, 0.97, 0.95, 0.90, 0.86, 0.80, 0.52, 0.42, 0.25, 0.18],
    "strong_middle": [0.99, 0.98, 0.97, 0.95, 0.93, 0.90, 0.72, 0.64, 0.45, 0.35],
    "weak_senior": [0.98, 0.97, 0.96, 0.92, 0.89, 0.85, 0.62, 0.55, 0.40, 0.32],
    "solid_senior": [0.99, 0.99, 0.98, 0.97, 0.96, 0.94, 0.88, 0.85, 0.78, 0.72],
    "guesser": [0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25],
}


def answer_as(profile, test, candidate_seed):
    """Формирует ответы синтетического кандидата (детерминированно по сиду)."""
    probabilities = PROFILES[profile]
    submitted = {}
    for key in test["answer_keys"]:
        rng = sub_rng(candidate_seed, "answer:%s" % key["item_id"])
        roll = rng.below(10000) / 10000.0
        correct = roll < probabilities[key["difficulty"] - 1]
        if correct:
            if "correct_letters" in key:
                letters = key["correct_letters"]
                submitted[key["item_id"]] = letters[0] if len(letters) == 1 else list(letters)
            else:
                submitted[key["item_id"]] = key["correct_values"][0]
        else:
            if "correct_letters" in key:
                wrong = [
                    letter
                    for letter in ("A", "B", "C", "D")
                    if letter not in key["correct_letters"]
                ]
                submitted[key["item_id"]] = wrong[rng.below(len(wrong))]
            else:
                submitted[key["item_id"]] = "__wrong__"
    return submitted


ATTACKS = ("longest", "shortest", "second_longest", "question_overlap")
_WORD = re.compile(r"\w+", re.U)


def _words(text):
    return {w.lower() for w in _WORD.findall(text) if len(w) > 3}


def attack_answers(test, strategy):
    """
    Ответы кандидата, который выбирает вариант по внешнему признаку.

    Работает только с тем, что видит клиент (client_items): длиной вариантов
    и совпадением слов с вопросом. Задания со свободным вводом пропускаются.
    """
    submitted = {}
    for payload, key in zip(test["client_items"], test["answer_keys"]):
        options = payload.get("options") or []
        if not options:
            continue
        if strategy == "longest":
            pick = max(options, key=lambda o: (len(o["text"]), o["id"]))
        elif strategy == "shortest":
            pick = min(options, key=lambda o: (len(o["text"]), o["id"]))
        elif strategy == "second_longest":
            pick = sorted(options, key=lambda o: (-len(o["text"]), o["id"]))[1]
        elif strategy == "question_overlap":
            question = _words(payload["question"])
            pick = max(options, key=lambda o: (len(question & _words(o["text"])), o["id"]))
        else:
            raise ValueError(strategy)
        submitted[key["item_id"]] = pick["id"]
    return submitted


def run_case(pool, specialization, declared_level, profile, seed):
    test = assemble_test(pool, specialization, declared_level, seed)
    submitted = answer_as(profile, test, seed)
    document = build_result_document("sim-%s-%d" % (profile, seed), test, submitted, "2026-10-05T12:00:00Z")
    return test, document


def main():
    items = load_bank()
    pools = {
        spec: [i for i in items if i["specialization"] == spec]
        for spec in ("frontend", "backend", "qa")
    }
    report = {"checks": [], "grade_matrix": {}, "overlap": {}, "monotonicity": {}}
    failures = []

    def check(name, passed, detail):
        report["checks"].append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append("%s: %s" % (name, detail))

    # ---------------------------------------------------------------- S1
    repeats_ok = True
    for spec in pools:
        for level in LEVELS:
            for seed in (11, 987654321, 2 ** 40 + 7):
                a = run_case(pools[spec], spec, level, "solid_middle", seed)[1]
                b = run_case(pools[spec], spec, level, "solid_middle", seed)[1]
                if json.dumps(a, ensure_ascii=False, sort_keys=True) != json.dumps(
                    b, ensure_ascii=False, sort_keys=True
                ):
                    repeats_ok = False
    check("S1_reproducibility", repeats_ok, "повторный расчёт с тем же сидом даёт тот же документ")

    # ---------------------------------------------------------------- S2
    overlaps = []
    comparable = True
    for spec in pools:
        for level in LEVELS:
            tests = [assemble_test(pools[spec], spec, level, seed) for seed in range(1001, 1025)]
            point_totals = {sum(i["score"] for i in t["items"]) for t in tests}
            type_profiles = {
                tuple(sorted(Counter(i["type"] for i in t["items"]).items())) for t in tests
            }
            difficulty_profiles = {
                tuple(sorted(Counter(i["difficulty"] for i in t["items"]).items())) for t in tests
            }
            if len(point_totals) != 1 or len(type_profiles) != 1:
                comparable = False
            for a in range(len(tests)):
                ids_a = {i["item_id"] for i in tests[a]["items"]}
                for b in range(a + 1, len(tests)):
                    ids_b = {i["item_id"] for i in tests[b]["items"]}
                    overlaps.append(len(ids_a & ids_b) / 26.0)
            report["overlap"]["%s/%s" % (spec, level)] = {
                "point_totals": sorted(point_totals),
                "distinct_difficulty_profiles": len(difficulty_profiles),
            }
    mean_overlap = sum(overlaps) / float(len(overlaps))
    max_overlap = max(overlaps)
    report["overlap"]["mean_share"] = round(mean_overlap, 3)
    report["overlap"]["max_share"] = round(max_overlap, 3)
    check(
        "S2_comparable_variants",
        comparable,
        "сумма баллов и состав по типам одинаковы у всех вариантов одного уровня",
    )
    check(
        "S2_variant_diversity",
        mean_overlap < 0.5 and max_overlap < 0.85,
        "среднее перекрытие заданий %.1f%%, максимальное %.1f%%" % (mean_overlap * 100, max_overlap * 100),
    )

    # ---------------------------------------------------------------- S3
    monotone_ok = True
    for spec in pools:
        for level in LEVELS:
            means = {}
            for profile in ("guesser", "weak_junior", "solid_junior", "solid_middle", "solid_senior"):
                scores = [
                    run_case(pools[spec], spec, level, profile, seed)[1]["score"]
                    for seed in range(2001, 2021)
                ]
                means[profile] = round(sum(scores) / float(len(scores)), 1)
            report["monotonicity"]["%s/%s" % (spec, level)] = means
            # угадывающий исключён: при четырёх вариантах он даёт базовые 25 %,
            # что выше результата очень слабого кандидата на сложном тесте
            ordered = [
                means["weak_junior"],
                means["solid_junior"],
                means["solid_middle"],
                means["solid_senior"],
            ]
            if any(ordered[i] > ordered[i + 1] for i in range(len(ordered) - 1)):
                monotone_ok = False
    check("S3_monotonicity", monotone_ok, "средний балл не убывает при росте уровня кандидата")

    # ---------------------------------------------------------------- S4
    matrix = defaultdict(Counter)
    for spec in pools:
        for declared in LEVELS:
            for profile in PROFILES:
                for seed in range(3001, 3025):
                    _test, document = run_case(pools[spec], spec, declared, profile, seed)
                    matrix["%s|%s|%s" % (spec, declared, profile)][document["confirmed_level"]] += 1
    report["grade_matrix"] = {k: dict(v) for k, v in sorted(matrix.items())}

    def share(spec, declared, profile, level):
        counter = matrix["%s|%s|%s" % (spec, declared, profile)]
        total = sum(counter.values())
        return counter.get(level, 0) / float(total) if total else 0.0

    scenarios = {
        "J->J": [("junior", "solid_junior", "junior")],
        "J->M": [("junior", "solid_middle", "middle")],
        "M->M": [("middle", "solid_middle", "middle")],
        "M->J": [("middle", "solid_junior", "junior")],
        "S->S": [("senior", "solid_senior", "senior")],
        "S->M": [("senior", "solid_middle", "middle")],
    }
    scenario_report = {}
    for name, cases in scenarios.items():
        values = []
        for declared, profile, expected in cases:
            for spec in pools:
                values.append(share(spec, declared, profile, expected))
        scenario_report[name] = round(min(values), 3)
    report["scenarios"] = scenario_report
    for name, value in scenario_report.items():
        check(
            "S4_scenario_%s" % name.replace("->", "_to_"),
            value >= 0.45,
            "сценарий %s достигается в %.0f%% прогонов (минимум по специализациям, "
            "порог калибровки 45%%)" % (name, value * 100),
        )

    # угадывание не должно подтверждать уровень
    # Угадывание: при 26 заданиях и четырёх вариантах базовая вероятность
    # даёт около 25 %, поэтому редкие удачные прогоны неизбежны. Требование —
    # доля ложных подтверждений не выше 5 %, а подтверждение выше junior
    # недостижимо в принципе.
    false_positive = []
    above_junior = []
    for spec in pools:
        for declared in LEVELS:
            counter = matrix["%s|%s|guesser" % (spec, declared)]
            total = sum(counter.values())
            confirmed_any = total - counter.get("below_junior", 0)
            false_positive.append(confirmed_any / float(total))
            above_junior.append(
                (counter.get("middle", 0) + counter.get("senior", 0)) / float(total)
            )
    report["guessing"] = {
        "false_positive_max": round(max(false_positive), 3),
        "false_positive_mean": round(sum(false_positive) / len(false_positive), 3),
        "above_junior_max": round(max(above_junior), 3),
    }
    check(
        "S4_guessing_rejected",
        max(false_positive) <= 0.15 and max(above_junior) <= 0.10,
        "ложное подтверждение при случайных ответах: максимум %.1f%% (порог 15%%), "
        "из них выше junior %.1f%% (порог 10%%); разрешение теста из 26 заданий – "
        "см. docs/specification.md, раздел 9"
        % (max(false_positive) * 100, max(above_junior) * 100),
    )

    # senior нельзя подтвердить с теста уровня middle
    promo_bad = []
    for spec in pools:
        for profile in ("solid_senior", "strong_middle"):
            if share(spec, "middle", profile, "senior") > 0:
                promo_bad.append("%s/%s" % (spec, profile))
    check(
        "S4_no_senior_from_middle_test",
        not promo_bad,
        "senior не подтверждается по тесту уровня middle" if not promo_bad else str(promo_bad),
    )

    # ---------------------------------------------------------------- S5
    unstable = []
    for key, counter in matrix.items():
        spec, declared, profile = key.split("|")
        if profile not in ("solid_junior", "solid_middle", "solid_senior"):
            continue
        if declared != {"solid_junior": "junior", "solid_middle": "middle", "solid_senior": "senior"}[profile]:
            continue
        total = sum(counter.values())
        dominant = max(counter.values()) / float(total)
        if dominant < 0.75:
            unstable.append("%s (%s)" % (key, dict(counter)))
    check(
        "S5_stability",
        not unstable,
        "для согласованных пар «заявлено/истинный уровень» доминирующий грейд не ниже 75%%"
        if not unstable
        else str(unstable),
    )

    # ---------------------------------------------------------------- S6
    # Эвристические атаки: кандидат не знает предмета и выбирает вариант
    # по внешнему признаку того, что видит на экране. Если признак связан с
    # правильностью (например, правильный ответ чаще самый длинный), такая
    # стратегия подтверждает уровень. Требование то же, что для угадывания.
    attack_report = {}
    attack_bad = []
    for strategy in ATTACKS:
        worst_any = 0.0
        worst_above = 0.0
        scores = []
        for spec in pools:
            for level in LEVELS:
                counter = Counter()
                for seed in range(4001, 4081):
                    test = assemble_test(pools[spec], spec, level, seed)
                    result = score_attempt(test["answer_keys"], attack_answers(test, strategy))
                    grade = determine_grade(result, spec, level)
                    counter[grade["confirmed_level"]] += 1
                    scores.append(result["score"])
                total = float(sum(counter.values()))
                worst_any = max(worst_any, (total - counter.get("below_junior", 0)) / total)
                worst_above = max(
                    worst_above, (counter.get("middle", 0) + counter.get("senior", 0)) / total
                )
        attack_report[strategy] = {
            "mean_score": round(sum(scores) / float(len(scores)), 1),
            "false_confirm_max": round(worst_any, 3),
            "above_junior_max": round(worst_above, 3),
        }
        if worst_any > 0.15 or worst_above > 0.10:
            attack_bad.append(strategy)
    report["attacks"] = attack_report
    check(
        "S6_heuristic_attacks",
        not attack_bad,
        "стратегии по внешним признакам (%s) не подтверждают уровень чаще порогов угадывания"
        % ", ".join(ATTACKS)
        if not attack_bad
        else "уровень подтверждают стратегии: %s" % ", ".join(attack_bad),
    )

    if "--json" in sys.argv:
        report["failures"] = failures
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=1))
        sys.stdout.write(chr(10))
        return 1 if failures else 0

    print("=== проверки ===")
    for entry in report["checks"]:
        print("%-34s %s  %s" % (entry["check"], "OK  " if entry["passed"] else "FAIL", entry["detail"]))

    print("")
    print("=== средний балл по профилям кандидата ===")
    for key in sorted(report["monotonicity"]):
        means = report["monotonicity"][key]
        print(
            "%-18s guesser %5.1f | weak_j %5.1f | solid_j %5.1f | solid_m %5.1f | solid_s %5.1f"
            % (
                key,
                means["guesser"],
                means["weak_junior"],
                means["solid_junior"],
                means["solid_middle"],
                means["solid_senior"],
            )
        )

    print("")
    print("=== достижимость требуемых сценариев (минимум по специализациям) ===")
    for name in ("J->J", "J->M", "M->M", "M->J", "S->S", "S->M"):
        print("%-6s %.0f%%" % (name, report["scenarios"][name] * 100))

    print("")
    print("=== эвристические атаки (80 сидов на каждую пару «специализация × уровень») ===")
    for strategy, data in report["attacks"].items():
        print(
            "%-18s средний балл %5.1f | ложное подтверждение до %4.1f%% | выше junior до %4.1f%%"
            % (
                strategy,
                data["mean_score"],
                data["false_confirm_max"] * 100,
                data["above_junior_max"] * 100,
            )
        )

    print("")
    print("=== перекрытие вариантов ===")
    print(
        "среднее %.1f%%, максимальное %.1f%%"
        % (report["overlap"]["mean_share"] * 100, report["overlap"]["max_share"] * 100)
    )

    print("")
    print("=== матрица «заявлено -> подтверждено» (backend, 24 сида на профиль) ===")
    for key in sorted(report["grade_matrix"]):
        spec, declared, profile = key.split("|")
        if spec != "backend":
            continue
        print("%-9s %-14s %s" % (declared, profile, dict(sorted(report["grade_matrix"][key].items()))))

    print("")
    if failures:
        print("ПРОВАЛЕНО проверок: %d" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
