"""
Пересборка отчётов и эталонных примеров в dist/.

Создаёт:
  dist/validation_report.txt   вывод tools/validate_bank.py
  dist/simulation_report.txt   вывод tools/simulate_candidates.py
  dist/simulation_report.json  то же машиночитаемо
  dist/example_result.json     полный документ результата: backend/middle, сид 184729
  dist/example_scenarios.json  18 эталонных случаев: 6 ситуаций × 3 специализации

Все файлы пишутся в UTF-8 и полностью воспроизводимы: синтетические
ответы детерминированы сидом (tools/simulate_candidates.py, answer_as).

Запуск:
    python tools/build_reports.py
"""

import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulate_candidates
import validate_bank
from assemble_test import assemble_test, build_result_document
from bank_lib import load_bank

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
FINISHED_AT = "2026-10-05T12:00:00Z"

# Ситуация, заявленный уровень, модель кандидата, ожидаемый подтверждённый уровень.
SCENARIOS = (
    ("J->J", "junior", "solid_junior", "junior"),
    ("J->M", "junior", "solid_middle", "middle"),
    ("M->M", "middle", "solid_middle", "middle"),
    ("M->J", "middle", "solid_junior", "junior"),
    ("S->S", "senior", "solid_senior", "senior"),
    ("S->M", "senior", "solid_middle", "middle"),
)
FIRST_SEED = 5001
SEED_SEARCH_LIMIT = 200


def write_text(name, text):
    with open(os.path.join(DIST, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(name, data):
    write_text(name, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def capture(func, *args):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = func(*args)
    return code, buffer.getvalue()


def result_for(pool, spec, level, profile, seed, candidate_id):
    test = assemble_test(pool, spec, level, seed)
    submitted = simulate_candidates.answer_as(profile, test, seed)
    return build_result_document(candidate_id, test, submitted, FINISHED_AT)


def build_scenarios(pools):
    rows = []
    for name, declared, profile, expected in SCENARIOS:
        for spec in ("frontend", "backend", "qa"):
            for seed in range(FIRST_SEED, FIRST_SEED + SEED_SEARCH_LIMIT):
                doc = result_for(pools[spec], spec, declared, profile, seed, "scenario-%s" % name)
                if doc["confirmed_level"] == expected:
                    break
            else:
                raise RuntimeError("ситуация %s/%s не найдена за %d сидов" % (name, spec, SEED_SEARCH_LIMIT))
            rows.append(
                {
                    "scenario": name,
                    "specialization": spec,
                    "declared_level": declared,
                    "candidate_model": profile,
                    "seed": seed,
                    "score": doc["score"],
                    "confirmed_level": doc["confirmed_level"],
                    "outcome": doc["outcome"],
                    "competencies": doc["competencies"],
                    "metrics": doc["grade_decision"]["metrics"],
                }
            )
    return rows


def main():
    if not os.path.isdir(DIST):
        os.makedirs(DIST)
    items = load_bank()
    pools = {spec: [i for i in items if i["specialization"] == spec] for spec in ("frontend", "backend", "qa")}

    code_v, text_v = capture(validate_bank.main)
    write_text("validation_report.txt", text_v)

    sys_argv = sys.argv
    try:
        sys.argv = [sys_argv[0]]
        code_s, text_s = capture(simulate_candidates.main)
        sys.argv = [sys_argv[0], "--json"]
        _code, json_s = capture(simulate_candidates.main)
    finally:
        sys.argv = sys_argv
    write_text("simulation_report.txt", text_s)
    write_text("simulation_report.json", json_s)

    example = result_for(
        pools["backend"], "backend", "middle", "solid_middle", 184729, "c7f1e2d0-4a6b-4c21-9e8f-0b1d2c3e4f55"
    )
    write_json("example_result.json", example)
    write_json("example_scenarios.json", build_scenarios(pools))

    print("validation_report.txt: код %d" % code_v)
    print("simulation_report.txt / .json: код %d" % code_s)
    print("example_result.json, example_scenarios.json обновлены")
    return 1 if (code_v or code_s) else 0


if __name__ == "__main__":
    sys.exit(main())
