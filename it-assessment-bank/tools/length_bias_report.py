"""
Отчёт по подсказке «правильный вариант самый длинный».

Выводит формы, в которых правильный вариант существенно длиннее остальных,
в порядке убывания величины подсказки. Это рабочий список для редактуры:
избыточную детализацию из правильного варианта переносят в explanation,
а неверные варианты доводят до сопоставимого объёма за счёт реального
содержания (описания типичной ошибки), не добавляя пустых слов.

Запуск:
    python tools/length_bias_report.py            # топ-40
    python tools/length_bias_report.py --all      # все формы с подсказкой
    python tools/length_bias_report.py --csv      # csv для распределения работы
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_lib import forms_of, load_bank

THRESHOLD = 1.3  # во сколько раз правильный вариант длиннее ближайшего неверного


def collect(items):
    rows = []
    for item in items:
        if item["validation_type"] != "single_choice":
            continue
        for form in forms_of(item):
            if len(form["options"]) != 4 or len(form["correct_answer"]) != 1:
                continue
            lengths = {o["id"]: len(o["text"]) for o in form["options"]}
            correct = form["correct_answer"][0]
            correct_len = lengths[correct]
            others = [v for k, v in lengths.items() if k != correct]
            ratio = correct_len / float(max(others)) if max(others) else 0.0
            rows.append(
                {
                    "item_id": item["id"],
                    "variant_id": form["variant_id"],
                    "specialization": item["specialization"],
                    "level": item["level"],
                    "type": item["type"],
                    "correct_len": correct_len,
                    "max_other_len": max(others),
                    "avg_other_len": round(sum(others) / float(len(others))),
                    "ratio": round(ratio, 2),
                }
            )
    rows.sort(key=lambda r: -r["ratio"])
    return rows


def main():
    rows = collect(load_bank())
    flagged = [r for r in rows if r["ratio"] > THRESHOLD]

    if "--csv" in sys.argv:
        print("item_id;variant_id;specialization;level;type;correct_len;max_other_len;ratio")
        for row in flagged:
            print(
                "%s;%s;%s;%s;%s;%d;%d;%.2f"
                % (
                    row["item_id"],
                    row["variant_id"],
                    row["specialization"],
                    row["level"],
                    row["type"],
                    row["correct_len"],
                    row["max_other_len"],
                    row["ratio"],
                )
            )
        return 0

    limit = len(flagged) if "--all" in sys.argv else 40
    print(
        "форм всего: %d, с подсказкой (отношение > %.1f): %d (%.1f%%)"
        % (len(rows), THRESHOLD, len(flagged), 100.0 * len(flagged) / len(rows))
    )
    by_spec = {}
    for row in flagged:
        by_spec.setdefault(row["specialization"], 0)
        by_spec[row["specialization"]] += 1
    print("по специализациям: %s" % dict(sorted(by_spec.items())))
    print("")
    print("%-14s %-4s %-9s %-11s %6s %6s %6s" % ("item_id", "var", "spec", "level", "корр", "макс", "отнош"))
    for row in flagged[:limit]:
        print(
            "%-14s %-4s %-9s %-11s %6d %6d %6.2f"
            % (
                row["item_id"],
                row["variant_id"],
                row["specialization"],
                row["level"],
                row["correct_len"],
                row["max_other_len"],
                row["ratio"],
            )
        )
    if limit < len(flagged):
        print("... ещё %d форм (запустите с --all или --csv)" % (len(flagged) - limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
