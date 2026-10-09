"""
Сборка персонального теста, подсчёт результата и определение грейда.

Это эталонная реализация алгоритмов из docs/specification.md
(разделы 2–5: баллы, сборка теста, сид, грейд).
Код детерминирован: одинаковые (specialization, level, seed) дают
одинаковый тест вплоть до порядка вариантов ответа.

Использование из командной строки:
    python tools/assemble_test.py backend middle 184729
    python tools/assemble_test.py backend middle 184729 --json
"""

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_lib import check_answer, client_view, load_bank, render_item, sub_rng
from blueprint import (
    BLUEPRINT,
    COMPETENCY_CAP,
    COMPETENCY_MIN_POINTS,
    MANDATORY,
    MIN_COMPETENCIES,
    TEST_SIZE,
)
from grading import determine_grade

SPEC_PREFIX = {"frontend": "FE", "backend": "BE", "qa": "QA"}


# ==========================================================================
# 1. Сборка
# ==========================================================================

def _cell_key(cell):
    typ, dmin, dmax, _count = cell
    return (typ, dmin, dmax)


def _candidates(pool, typ, dmin, dmax):
    return [i for i in pool if i["type"] == typ and dmin <= i["difficulty"] <= dmax]


def assemble_test(pool, specialization, declared_level, seed):
    """
    Формирует персональный вариант теста.

    pool              — задания одной специализации (список словарей банка);
    declared_level    — заявленный кандидатом грейд;
    seed              — персональный сид (целое 64 бита).

    Возвращает словарь:
      test_id, seed, blueprint, items (payload для клиента),
      answer_keys (ключи проверки, на клиент не отдаются),
      selected_raw (исходные задания — для диагностики и валидации).
    """
    plan = BLUEPRINT[declared_level]
    mandatory = list(MANDATORY[specialization])

    used_ids = set()
    used_groups = set()
    competency_count = Counter()
    selected = []  # (cell_index, item)

    # Шаг 1. Для каждой ячейки плана готовим детерминированно перемешанный
    # список кандидатов. Домен сида включает ячейку, поэтому добавление
    # новой ячейки не меняет выбор в остальных.
    cell_pools = []
    for cell in plan:
        typ, dmin, dmax, _count = cell
        domain = "pool:%s:%s:%s:%d-%d" % (specialization, declared_level, typ, dmin, dmax)
        candidates = _candidates(pool, typ, dmin, dmax)
        candidates = sorted(candidates, key=lambda i: i["id"])
        cell_pools.append(sub_rng(seed, domain).shuffled(candidates))

    # Шаг 2. Основной проход. Ячейки обходятся в порядке плана; внутри ячейки
    # задания берутся из перемешанного списка. Кандидат допускается, если:
    #   * задание ещё не выбрано;
    #   * его version_group ещё не использована;
    #   * предел заданий на компетенцию не превышен.
    # Среди допустимых предпочитается задание компетенции, которая ещё
    # обязательна и не покрыта; затем — компетенции с наименьшим числом
    # уже выбранных заданий (выравнивание покрытия).
    def pick(cell_index, needed_mandatory):
        best = None
        best_rank = None
        for position, item in enumerate(cell_pools[cell_index]):
            if item["id"] in used_ids:
                continue
            group = item.get("version_group")
            if group and group in used_groups:
                continue
            if competency_count[item["competency"]] >= COMPETENCY_CAP:
                continue
            rank = (
                0 if item["competency"] in needed_mandatory else 1,
                competency_count[item["competency"]],
                position,
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = item
                if rank[0] == 0 and rank[1] == 0:
                    break  # лучшего кандидата уже не будет
        return best

    for cell_index, cell in enumerate(plan):
        _typ, _dmin, _dmax, count = cell
        for _ in range(count):
            needed = {c for c in mandatory if competency_count[c] == 0}
            item = pick(cell_index, needed)
            if item is None:
                raise RuntimeError(
                    "недостаточно заданий для ячейки %r (%s/%s)"
                    % (_cell_key(cell), specialization, declared_level)
                )
            used_ids.add(item["id"])
            if item.get("version_group"):
                used_groups.add(item["version_group"])
            competency_count[item["competency"]] += 1
            selected.append((cell_index, item))

    # Шаг 3. Ремонт покрытия обязательных компетенций.
    # Если какая-то обязательная компетенция не попала в выборку, ищем
    # замену: задание из той же ячейки, компетенция которого представлена
    # более одного раза, меняем на задание нужной компетенции.
    for competency in mandatory:
        if competency_count[competency] > 0:
            continue
        replaced = False
        for position, (cell_index, item) in enumerate(selected):
            if competency_count[item["competency"]] <= 1:
                continue
            replacement = None
            for candidate in cell_pools[cell_index]:
                if candidate["competency"] != competency:
                    continue
                if candidate["id"] in used_ids:
                    continue
                group = candidate.get("version_group")
                if group and group in used_groups and group != item.get("version_group"):
                    continue
                replacement = candidate
                break
            if replacement is None:
                continue
            used_ids.discard(item["id"])
            if item.get("version_group"):
                used_groups.discard(item["version_group"])
            competency_count[item["competency"]] -= 1
            used_ids.add(replacement["id"])
            if replacement.get("version_group"):
                used_groups.add(replacement["version_group"])
            competency_count[replacement["competency"]] += 1
            selected[position] = (cell_index, replacement)
            replaced = True
            break
        if not replaced:
            raise RuntimeError(
                "не удалось обеспечить покрытие обязательной компетенции %s (%s/%s)"
                % (competency, specialization, declared_level)
            )

    chosen = [item for _cell, item in selected]
    if len(chosen) != TEST_SIZE:
        raise RuntimeError("собрано %d заданий вместо %d" % (len(chosen), TEST_SIZE))
    if len({i["competency"] for i in chosen}) < MIN_COMPETENCIES:
        raise RuntimeError("покрыто меньше %d компетенций" % MIN_COMPETENCIES)

    # Шаг 4. Порядок показа: перемешиваем, но раскладываем так, чтобы
    # типы заданий чередовались (кандидат не получает 8 теорий подряд).
    order_rng = sub_rng(seed, "order:%s:%s" % (specialization, declared_level))
    by_type = defaultdict(list)
    for item in order_rng.shuffled(chosen):
        by_type[item["type"]].append(item)
    sequence = []
    type_cycle = ["situational", "practical", "theory"]
    while any(by_type[t] for t in type_cycle):
        for typ in type_cycle:
            if by_type[typ]:
                sequence.append(by_type[typ].pop(0))

    # Шаг 5. Рендеринг: выбор варианта задания и перестановка ответов.
    payloads = []
    keys = []
    for position, item in enumerate(sequence):
        payload, key = render_item(item, seed, position=position)
        payloads.append(payload)
        keys.append(key)

    return {
        # Метка попытки — односторонний хеш сида (64 бита SHA-256): метки
        # не совпадают (при seed % 1000000 они совпадали уже после тысячи
        # попыток) и не раскрывают сид. Сид раскрывать нельзя: по нему и
        # открытому банку клиент собрал бы свой тест вместе с ключами.
        # Платформа хранит попытку под собственным UUID.
        "test_id": make_test_id(specialization, declared_level, seed),
        "specialization": specialization,
        "declared_level": declared_level,
        "seed": seed,
        "blueprint": [list(cell) for cell in plan],
        "items": payloads,
        "client_items": [client_view(p) for p in payloads],
        "answer_keys": keys,
        "selected_raw": sequence,
    }


def make_test_id(specialization, declared_level, seed):
    """Метка попытки: префикс специализации, буква уровня и 16 hex-цифр SHA-256 от сида."""
    digest = hashlib.sha256(("assessment-test-id:%d" % seed).encode("ascii")).hexdigest()[:16].upper()
    return "%s-%s-%s" % (SPEC_PREFIX[specialization], declared_level[0].upper(), digest)


# ==========================================================================
# 2. Подсчёт результата
# ==========================================================================

def _bucket(difficulty):
    if difficulty <= 3:
        return "easy"
    if difficulty <= 6:
        return "mid"
    if difficulty <= 8:
        return "hard"
    return "top"


def score_attempt(answer_keys, submitted_by_item):
    """
    Считает результат попытки.

    answer_keys        — список ключей из assemble_test;
    submitted_by_item  — словарь item_id -> ответ кандидата
                         (отсутствие ключа трактуется как пропуск).

    Возвращает структуру с общим баллом, баллами по компетенциям
    и разрезами по сложности — всё, что нужно для определения грейда.
    """
    total_points = 0
    earned_points = 0
    chance_points = 0.0
    per_competency = defaultdict(lambda: {"earned": 0, "possible": 0, "items": 0, "correct": 0})
    per_bucket = defaultdict(lambda: {"earned": 0, "possible": 0, "items": 0, "correct": 0})
    answers = []

    for key in answer_keys:
        weight = key["score"]
        competency = key["competency"]
        bucket = _bucket(key["difficulty"])
        submitted = submitted_by_item.get(key["item_id"])
        is_correct = bool(check_answer(key, submitted)) if submitted is not None else False

        total_points += weight
        options_count = key.get("options_count") or 0
        if options_count > 1:
            chance_points += weight / float(options_count)
        per_competency[competency]["possible"] += weight
        per_competency[competency]["items"] += 1
        per_bucket[bucket]["possible"] += weight
        per_bucket[bucket]["items"] += 1
        if is_correct:
            earned_points += weight
            per_competency[competency]["earned"] += weight
            per_competency[competency]["correct"] += 1
            per_bucket[bucket]["earned"] += weight
            per_bucket[bucket]["correct"] += 1

        answers.append(
            {
                "item_id": key["item_id"],
                "variant_id": key["variant_id"],
                "competency": competency,
                "difficulty": key["difficulty"],
                "score": weight,
                "submitted": submitted,
                "is_correct": is_correct,
                "points_earned": weight if is_correct else 0,
            }
        )

    overall = round(100.0 * earned_points / total_points) if total_points else 0

    competencies = {}
    for competency, data in per_competency.items():
        competencies[competency] = {
            "score": round(100.0 * data["earned"] / data["possible"]) if data["possible"] else 0,
            "points_earned": data["earned"],
            "points_possible": data["possible"],
            "items": data["items"],
            "correct": data["correct"],
            "confidence": "normal" if data["possible"] >= COMPETENCY_MIN_POINTS else "low",
        }

    buckets = {}
    for name in ("easy", "mid", "hard", "top"):
        data = per_bucket.get(name, {"earned": 0, "possible": 0, "items": 0, "correct": 0})
        buckets[name] = {
            "points_earned": data["earned"],
            "points_possible": data["possible"],
            "items": data["items"],
            "correct": data["correct"],
            "rate": round(data["earned"] / float(data["possible"]), 4) if data["possible"] else None,
        }

    chance_baseline = round(100.0 * chance_points / total_points) if total_points else 0
    return {
        "points_earned": earned_points,
        "points_possible": total_points,
        "score": overall,
        "chance_baseline": chance_baseline,
        "competencies": competencies,
        "difficulty_buckets": buckets,
        "answers": answers,
    }


# ==========================================================================
# 3. Определение подтверждённого грейда
# ==========================================================================

# ==========================================================================
# 4. Итоговая структура результата кандидата
# ==========================================================================

def build_result_document(candidate_id, test, submitted_by_item, finished_at):
    """Собирает документ результата по схеме docs/specification.md, раздел 6."""
    result = score_attempt(test["answer_keys"], submitted_by_item)
    grade = determine_grade(result, test["specialization"], test["declared_level"])

    return {
        "schema_version": "1.0",
        "candidate_id": candidate_id,
        "test_id": test["test_id"],
        "specialization": test["specialization"],
        "declared_level": test["declared_level"],
        "confirmed_level": grade["confirmed_level"],
        "outcome": grade["outcome"],
        "score": result["score"],
        "points_earned": result["points_earned"],
        "points_possible": result["points_possible"],
        "competencies": {
            name: data["score"] for name, data in sorted(result["competencies"].items())
        },
        "competency_details": result["competencies"],
        "difficulty_buckets": result["difficulty_buckets"],
        "grade_decision": grade,
        "seed": test["seed"],
        "blueprint": test["blueprint"],
        "items": [
            {
                "position": payload["position"],
                "item_id": payload["item_id"],
                "variant_id": payload["variant_id"],
                "type": payload["type"],
                "competency": payload["competency"],
                "difficulty": payload["difficulty"],
                "score": payload["score"],
                "validation_type": payload["validation_type"],
            }
            for payload in test["items"]
        ],
        "answers": result["answers"],
        "finished_at": finished_at,
    }


# ==========================================================================
# CLI
# ==========================================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 3:
        print(__doc__)
        return 2
    specialization, level, seed = args[0], args[1], int(args[2])
    pool = [i for i in load_bank() if i["specialization"] == specialization]
    if not pool:
        print("неизвестная специализация: %s" % specialization)
        return 2
    test = assemble_test(pool, specialization, level, seed)

    if "--json" in sys.argv:
        out = {k: v for k, v in test.items() if k != "selected_raw"}
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=1))
        sys.stdout.write("\n")
        return 0

    print("test_id: %s  seed: %d  заданий: %d" % (test["test_id"], seed, len(test["items"])))
    print("компетенции: %s" % ", ".join(sorted({i["competency"] for i in test["items"]})))
    counts = Counter(i["type"] for i in test["items"])
    print("по типам: %s" % dict(sorted(counts.items())))
    print("сумма баллов: %d" % sum(i["score"] for i in test["items"]))
    print("")
    for payload in test["items"]:
        print(
            "%2d. [%s d%d %s/%s] %s"
            % (
                payload["position"] + 1,
                payload["item_id"],
                payload["difficulty"],
                payload["type"][:4],
                payload["competency"],
                payload["question"][:90],
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
