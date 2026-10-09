"""
Анализ заданий по реальным попыткам: трудность и дискриминативность.

Для каждого задания банка по завершённым попыткам платформы:
  * n – сколько раз задание показано;
  * p – доля верных ответов (наблюдаемая трудность);
  * r – дискриминативность: точечно-бисериальная корреляция верности
    ответа на задание с долей баллов за остальные задания той же попытки.
    Считается внутри когорты «специализация × уровень теста» (тесты разных
    уровней несопоставимы по сумме), затем усредняется с весом n.

Признаки для ревизии задания (при n ≥ --min-n):
  * r < 0,10 – задание плохо разделяет сильных и слабых;
  * r < 0 – сильные отвечают хуже слабых: вероятна ошибка в ключе;
  * p > 0,95 или p < 0,05 – слишком лёгкое или слишком трудное;
  * заявленная сложность расходится с наблюдаемой (p сильно отличается от
    средней p заданий той же сложности).

На демо-данных (scripts/seed_demo.py) ответы смоделированы, поэтому
отчёт показывает механизм; содержательные выводы о заданиях – после
пилота на реальных кандидатах.

Запуск (из каталога backend):
    python -m scripts.item_analysis [--min-n 20]
Отчёт: reports/item_analysis.md
"""

import argparse
import logging
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def point_biserial(flags: list[int], values: list[float]) -> float | None:
    n = len(flags)
    if n < 3:
        return None
    ones = [v for f, v in zip(flags, values, strict=True) if f]
    zeros = [v for f, v in zip(flags, values, strict=True) if not f]
    if not ones or not zeros:
        return None
    sd = statistics.pstdev(values)
    if sd == 0:
        return None
    p = len(ones) / n
    return (statistics.mean(ones) - statistics.mean(zeros)) / sd * math.sqrt(p * (1 - p))


def analyse(min_n: int) -> dict:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Attempt, AttemptAnswer
    from app.services.bank import bank

    b = bank()
    db = SessionLocal()
    attempts = {a.id: a for a in db.scalars(select(Attempt).where(Attempt.status == "finished"))}
    # (item_id, cohort) -> [(верно, доля баллов за остальные задания)]
    pairs: dict = defaultdict(list)
    for row in db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(list(attempts)))):
        attempt = attempts[row.attempt_id]
        weight = attempt.items[row.position]["score"]
        earned = (attempt.points_earned or 0) - (weight if row.is_correct else 0)
        possible = (attempt.points_possible or 0) - weight
        if possible <= 0:
            continue
        cohort = (attempt.specialization, attempt.declared_level)
        pairs[(row.item_id, cohort)].append((1 if row.is_correct else 0, earned / possible))
    db.close()

    items = {}
    for (item_id, _cohort), data in pairs.items():
        entry = items.setdefault(item_id, {"n": 0, "correct": 0, "r_parts": []})
        entry["n"] += len(data)
        entry["correct"] += sum(f for f, _v in data)
        r = point_biserial([f for f, _v in data], [v for _f, v in data])
        if r is not None:
            entry["r_parts"].append((r, len(data)))

    rows = []
    for item_id, entry in items.items():
        meta = b.by_id.get(item_id, {})
        parts = entry["r_parts"]
        r = sum(x * w for x, w in parts) / sum(w for _x, w in parts) if parts else None
        rows.append(
            {
                "item_id": item_id,
                "specialization": meta.get("specialization"),
                "difficulty": meta.get("difficulty"),
                "competency": meta.get("competency"),
                "n": entry["n"],
                "p": entry["correct"] / entry["n"],
                "r": r,
            }
        )
    enough = [r for r in rows if r["n"] >= min_n]
    by_difficulty = defaultdict(list)
    for r in enough:
        by_difficulty[r["difficulty"]].append(r["p"])
    mean_p = {d: statistics.mean(v) for d, v in by_difficulty.items()}
    for r in enough:
        flags = []
        if r["r"] is not None and r["r"] < 0:
            flags.append("r < 0: проверить ключ")
        elif r["r"] is not None and r["r"] < 0.10:
            flags.append("слабо разделяет")
        if r["p"] > 0.95:
            flags.append("слишком лёгкое")
        if r["p"] < 0.05:
            flags.append("слишком трудное")
        if abs(r["p"] - mean_p[r["difficulty"]]) > 0.30:
            flags.append("сложность расходится с наблюдаемой")
        r["flags"] = flags
    return {"rows": rows, "enough": enough, "mean_p": mean_p, "attempts": len(attempts), "bank_items": len(b.items)}


def write_report(result: dict, min_n: int) -> str:
    enough = result["enough"]
    with_r = [r for r in enough if r["r"] is not None]
    flagged = [r for r in enough if r["flags"]]
    diffs = sorted(result["mean_p"])
    corr = None
    if len(enough) > 2:
        xs = [r["difficulty"] for r in enough]
        ys = [r["p"] for r in enough]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den if den else None
    lines = [
        "# Анализ заданий по попыткам",
        "",
        "Сформирован `scripts/item_analysis.py`. Завершённых попыток: %d. Заданий показано хотя бы раз: %d из %d; "
        "с n ≥ %d: %d." % (result["attempts"], len(result["rows"]), result["bank_items"], min_n, len(enough)),
        "",
        "## Сводка",
        "",
        "| Показатель | Значение |",
        "|---|---|",
        "| медиана дискриминативности r | %s |" % ("%.2f" % statistics.median([r["r"] for r in with_r]) if with_r else "–"),
        "| доля заданий с r ≥ 0,20 | %s |" % ("%.0f %%" % (100 * sum(1 for r in with_r if r["r"] >= 0.2) / len(with_r)) if with_r else "–"),
        "| доля заданий с r < 0,10 | %s |" % ("%.0f %%" % (100 * sum(1 for r in with_r if r["r"] < 0.1) / len(with_r)) if with_r else "–"),
        "| корреляция заявленной сложности и доли верных | %s |" % ("%.2f" % corr if corr is not None else "–"),
        "| заданий с признаками для ревизии | %d |" % len(flagged),
        "",
        "## Доля верных ответов по заявленной сложности",
        "",
        "| Сложность | " + " | ".join(str(d) for d in diffs) + " |",
        "|---|" + "---|" * len(diffs),
        "| p | " + " | ".join("%.2f" % result["mean_p"][d] for d in diffs) + " |",
        "",
        "## Задания с признаками для ревизии",
        "",
    ]
    if flagged:
        lines += ["| Задание | Сложность | Компетенция | n | p | r | Признаки |", "|---|---|---|---|---|---|---|"]
        for r in sorted(flagged, key=lambda x: (x["r"] if x["r"] is not None else 9)):
            lines.append("| %s | %s | %s | %d | %.2f | %s | %s |" % (
                r["item_id"], r["difficulty"], r["competency"], r["n"], r["p"],
                "%.2f" % r["r"] if r["r"] is not None else "–", "; ".join(r["flags"])))
    else:
        lines.append("Нет.")
    lines += [
        "",
        "На демо-данных ответы смоделированы по сложности задания и силе кандидата, поэтому отчёт показывает работу "
        "механизма. Выводы о конкретных заданиях – после пилота на реальных кандидатах; тогда задания с признаками "
        "пересматриваются, а при изменении формулировки получают новую версию (version_group банка).",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Анализ заданий по попыткам")
    parser.add_argument("--min-n", type=int, default=20, help="минимум показов задания для выводов")
    args = parser.parse_args()
    logging.disable(logging.INFO)
    result = analyse(args.min_n)
    out = ROOT / "reports" / "item_analysis.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(write_report(result, args.min_n), encoding="utf-8", newline="\n")
    print("Отчёт: reports/item_analysis.md (заданий с n ≥ %d: %d)" % (args.min_n, len(result["enough"])))


if __name__ == "__main__":
    main()
