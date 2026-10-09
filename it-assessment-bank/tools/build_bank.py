"""
Сборка банка в единый файл и расчёт статистики.

Создаёт:
    dist/bank.json        – все 720 заданий одним документом с метаданными;
    dist/statistics.json  – статистика банка машиночитаемо;
    dist/statistics.md    – та же статистика в виде таблиц.

Запуск:  python tools/build_bank.py
"""

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_lib import LEVELS, SPECIALIZATIONS, TYPES, forms_of, load_bank
from blueprint import COMPETENCIES, CRITICAL, KEY, MANDATORY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_VERSION = "1.0"
BANK_VERSION = "1.1.0"

FIELD_ORDER = [
    "id",
    "specialization",
    "level",
    "type",
    "competency",
    "difficulty",
    "question",
    "language",
    "code",
    "options",
    "correct_answer",
    "answer_normalization",
    "score",
    "explanation",
    "tags",
    "version_group",
    "seedable",
    "seed_parameters",
    "validation_type",
    "variants",
]


def normalize_item(item):
    out = {}
    for field in FIELD_ORDER:
        if field in item:
            out[field] = item[field]
    return out


def compute_statistics(items):
    stats = {}
    stats["total_items"] = len(items)
    stats["total_rendered_forms"] = sum(len(forms_of(i)) for i in items)

    stats["by_specialization"] = dict(Counter(i["specialization"] for i in items))
    stats["by_level"] = dict(Counter(i["level"] for i in items))
    stats["by_type"] = dict(Counter(i["type"] for i in items))

    matrix = defaultdict(lambda: defaultdict(Counter))
    for item in items:
        matrix[item["specialization"]][item["level"]][item["type"]] += 1
    stats["by_specialization_level_type"] = {
        spec: {level: dict(types) for level, types in sorted(levels.items())}
        for spec, levels in sorted(matrix.items())
    }

    stats["by_competency"] = {
        spec: dict(
            sorted(
                Counter(
                    i["competency"] for i in items if i["specialization"] == spec
                ).items()
            )
        )
        for spec in SPECIALIZATIONS
    }
    comp_level = {}
    for spec in SPECIALIZATIONS:
        comp_level[spec] = {}
        for competency in COMPETENCIES[spec]:
            counter = Counter(
                i["level"]
                for i in items
                if i["specialization"] == spec and i["competency"] == competency
            )
            comp_level[spec][competency] = {level: counter.get(level, 0) for level in LEVELS}
    stats["by_competency_level"] = comp_level

    stats["by_difficulty"] = {
        str(d): c
        for d, c in sorted(Counter(i["difficulty"] for i in items).items())
    }
    stats["by_difficulty_per_specialization"] = {
        spec: {
            str(d): c
            for d, c in sorted(
                Counter(
                    i["difficulty"] for i in items if i["specialization"] == spec
                ).items()
            )
        }
        for spec in SPECIALIZATIONS
    }

    stats["by_validation_type"] = dict(Counter(i["validation_type"] for i in items))
    stats["by_score"] = {
        str(s): c for s, c in sorted(Counter(i["score"] for i in items).items())
    }

    stats["seedable_items"] = sum(1 for i in items if i.get("seedable"))
    stats["items_with_code"] = sum(1 for i in items if i.get("code"))
    stats["items_with_variants"] = sum(1 for i in items if i.get("variants"))
    stats["total_variants"] = sum(len(i.get("variants") or []) for i in items)
    seed_params = Counter()
    for item in items:
        for parameter in item.get("seed_parameters") or []:
            seed_params[parameter] += 1
    stats["seed_parameters_usage"] = dict(sorted(seed_params.items()))

    groups = defaultdict(list)
    for item in items:
        if item.get("version_group"):
            groups[item["version_group"]].append(item)
    stats["version_groups"] = {
        "count": len(groups),
        "items_in_groups": sum(len(v) for v in groups.values()),
        "items_without_group": sum(1 for i in items if not i.get("version_group")),
        "max_group_size": max([len(v) for v in groups.values()] or [0]),
    }

    letters = Counter()
    letters_per_spec = defaultdict(Counter)
    for item in items:
        for form in forms_of(item):
            if form["options"] and item["validation_type"] == "single_choice":
                letters[form["correct_answer"][0]] += 1
                letters_per_spec[item["specialization"]][form["correct_answer"][0]] += 1
    total_letters = sum(letters.values())
    stats["correct_answer_distribution"] = {
        "total_forms": total_letters,
        "counts": dict(sorted(letters.items())),
        "shares_percent": {
            letter: round(100.0 * count / total_letters, 1)
            for letter, count in sorted(letters.items())
        },
        "per_specialization": {
            spec: dict(sorted(counter.items()))
            for spec, counter in sorted(letters_per_spec.items())
        },
    }

    # все задания проверяются автоматически по построению: в банке нет
    # свободных текстовых ответов, требующих экспертной оценки
    auto = Counter()
    for item in items:
        auto[item["validation_type"]] += 1
    stats["automatically_checkable"] = {
        "items": len(items),
        "share_percent": 100.0,
        "by_validation_type": dict(sorted(auto.items())),
        "requires_human_review": 0,
        "requires_external_service": 0,
    }

    stats["competency_roles"] = {
        spec: {
            "mandatory": MANDATORY[spec],
            "key": KEY[spec],
            "critical": CRITICAL[spec],
        }
        for spec in SPECIALIZATIONS
    }

    # подсказка по длине вариантов — известное ограничение, см. docs/specification.md, раздел 9
    longest_correct = 0
    strong_cue = 0
    considered = 0
    for item in items:
        if item["validation_type"] != "single_choice":
            continue
        for form in forms_of(item):
            if len(form["options"]) != 4 or len(form["correct_answer"]) != 1:
                continue
            considered += 1
            lengths = {o["id"]: len(o["text"]) for o in form["options"]}
            correct = form["correct_answer"][0]
            others_max = max(v for k, v in lengths.items() if k != correct)
            if lengths[correct] >= max(lengths.values()):
                longest_correct += 1
            if lengths[correct] > 1.8 * others_max:
                strong_cue += 1
    stats["option_length_bias"] = {
        "forms_considered": considered,
        "correct_is_longest": longest_correct,
        "correct_is_longest_percent": round(100.0 * longest_correct / considered, 1),
        "strong_cue_forms": strong_cue,
        "strong_cue_percent": round(100.0 * strong_cue / considered, 1),
        "target_percent": 45.0,
        "status": "known_limitation",
    }
    return stats


def render_markdown(stats):
    lines = []
    out = lines.append
    out("# Статистика банка заданий")
    out("")
    out("Файл сформирован автоматически: `python tools/build_bank.py`.")
    out("Машиночитаемая версия – `dist/statistics.json`.")
    out("")
    out("## 1. Общие числа")
    out("")
    out("| Показатель | Значение |")
    out("|---|---|")
    out("| Всего заданий | %d |" % stats["total_items"])
    out("| Всего конкретных форм (задания + варианты) | %d |" % stats["total_rendered_forms"])
    out("| Заданий с кодом | %d |" % stats["items_with_code"])
    out("| Заданий с несколькими вариантами | %d |" % stats["items_with_variants"])
    out("| Дополнительных вариантов | %d |" % stats["total_variants"])
    out("| Seedable заданий | %d |" % stats["seedable_items"])
    out("| Проверяются автоматически | %d (100%%) |" % stats["automatically_checkable"]["items"])
    out("| Требуют ручной проверки | %d |" % stats["automatically_checkable"]["requires_human_review"])
    out("| Требуют внешних сервисов | %d |" % stats["automatically_checkable"]["requires_external_service"])
    out("")

    out("## 2. По специализациям, уровням и типам")
    out("")
    out("| Специализация | Всего | junior | middle | senior | theory | situational | practical |")
    out("|---|---|---|---|---|---|---|---|")
    for spec in SPECIALIZATIONS:
        levels = stats["by_specialization_level_type"][spec]
        total = sum(sum(t.values()) for t in levels.values())
        per_level = {level: sum(levels[level].values()) for level in LEVELS}
        per_type = {
            typ: sum(levels[level].get(typ, 0) for level in LEVELS) for typ in TYPES
        }
        out(
            "| %s | %d | %d | %d | %d | %d | %d | %d |"
            % (
                spec,
                total,
                per_level["junior"],
                per_level["middle"],
                per_level["senior"],
                per_type["theory"],
                per_type["situational"],
                per_type["practical"],
            )
        )
    out(
        "| **итого** | **%d** | **%d** | **%d** | **%d** | **%d** | **%d** | **%d** |"
        % (
            stats["total_items"],
            stats["by_level"]["junior"],
            stats["by_level"]["middle"],
            stats["by_level"]["senior"],
            stats["by_type"]["theory"],
            stats["by_type"]["situational"],
            stats["by_type"]["practical"],
        )
    )
    out("")

    out("## 3. Матрица «уровень × тип» по специализациям")
    out("")
    for spec in SPECIALIZATIONS:
        out("**%s**" % spec)
        out("")
        out("| Уровень | theory | situational | practical | всего |")
        out("|---|---|---|---|---|")
        levels = stats["by_specialization_level_type"][spec]
        for level in LEVELS:
            row = levels[level]
            out(
                "| %s | %d | %d | %d | %d |"
                % (
                    level,
                    row.get("theory", 0),
                    row.get("situational", 0),
                    row.get("practical", 0),
                    sum(row.values()),
                )
            )
        out("")

    out("## 4. По компетенциям")
    out("")
    for spec in SPECIALIZATIONS:
        out("**%s**" % spec)
        out("")
        out("| Компетенция | junior | middle | senior | всего | роль |")
        out("|---|---|---|---|---|---|")
        roles = stats["competency_roles"][spec]
        for competency in COMPETENCIES[spec]:
            per_level = stats["by_competency_level"][spec][competency]
            total = sum(per_level.values())
            role = []
            if competency in roles["mandatory"]:
                role.append("обязательная")
            if competency in roles["key"]:
                role.append("ключевая")
            if competency in roles["critical"]:
                role.append("критическая")
            out(
                "| %s | %d | %d | %d | %d | %s |"
                % (
                    competency,
                    per_level["junior"],
                    per_level["middle"],
                    per_level["senior"],
                    total,
                    ", ".join(role) or "поддерживающая",
                )
            )
        out("")

    out("## 5. Распределение difficulty 1-10")
    out("")
    out("| difficulty | баллов за задание | frontend | backend | qa | всего |")
    out("|---|---|---|---|---|---|")
    for difficulty in range(1, 11):
        key = str(difficulty)
        score = 1 if difficulty <= 3 else 2 if difficulty <= 6 else 3 if difficulty <= 8 else 4
        row = [
            stats["by_difficulty_per_specialization"][spec].get(key, 0)
            for spec in SPECIALIZATIONS
        ]
        out(
            "| %d | %d | %d | %d | %d | %d |"
            % (difficulty, score, row[0], row[1], row[2], stats["by_difficulty"].get(key, 0))
        )
    out("")

    out("## 6. Типы автоматической проверки")
    out("")
    out("| validation_type | заданий |")
    out("|---|---|")
    for vtype, count in sorted(stats["by_validation_type"].items()):
        out("| %s | %d |" % (vtype, count))
    out("")

    out("## 7. Сиды и варианты")
    out("")
    out("| Показатель | Значение |")
    out("|---|---|")
    out("| version_group всего | %d |" % stats["version_groups"]["count"])
    out("| заданий в группах | %d |" % stats["version_groups"]["items_in_groups"])
    out("| заданий без группы | %d |" % stats["version_groups"]["items_without_group"])
    out("| наибольшая группа | %d |" % stats["version_groups"]["max_group_size"])
    out("")
    out("| seed_parameter | заданий |")
    out("|---|---|")
    for parameter, count in sorted(stats["seed_parameters_usage"].items()):
        out("| %s | %d |" % (parameter, count))
    out("")

    out("## 8. Распределение правильных ответов")
    out("")
    distribution = stats["correct_answer_distribution"]
    out("Считается по всем конкретным формам с вариантами ответа (%d)." % distribution["total_forms"])
    out("")
    out("| Буква | форм | доля |")
    out("|---|---|---|")
    for letter in "ABCD":
        out(
            "| %s | %d | %.1f%% |"
            % (letter, distribution["counts"].get(letter, 0), distribution["shares_percent"].get(letter, 0.0))
        )
    out("")
    out("| Специализация | A | B | C | D |")
    out("|---|---|---|---|---|")
    for spec, counter in sorted(distribution["per_specialization"].items()):
        out(
            "| %s | %d | %d | %d | %d |"
            % (spec, counter.get("A", 0), counter.get("B", 0), counter.get("C", 0), counter.get("D", 0))
        )
    out("")

    out("## 9. Известное ограничение: подсказка по длине варианта")
    out("")
    bias = stats["option_length_bias"]
    out(
        "В %.1f%% форм (%d из %d) правильный вариант является самым длинным, "
        "а в %.1f%% он длиннее ближайшего по длине неверного варианта более чем "
        "в 1,8 раза."
        % (
            bias["correct_is_longest_percent"],
            bias["correct_is_longest"],
            bias["forms_considered"],
            bias["strong_cue_percent"],
        )
    )
    out("")
    out(
        "Это даёт кандидату нежелательную подсказку. Целевое значение – не более "
        "%.0f%% (случайный уровень для четырёх вариантов – 25%%). Порядок устранения "
        "описан в `docs/specification.md`, раздел 9; "
        "список форм в порядке убывания величины подсказки выдаёт "
        "`python tools/length_bias_report.py`." % bias["target_percent"]
    )
    out("")
    return "\n".join(lines) + "\n"


def main():
    items = load_bank()
    items.sort(key=lambda i: i["id"])
    clean = [normalize_item(i) for i in items]

    dist_dir = os.path.join(ROOT, "dist")
    if not os.path.isdir(dist_dir):
        os.makedirs(dist_dir)

    bank_doc = {
        "schema_version": SCHEMA_VERSION,
        "bank_version": BANK_VERSION,
        "specializations": list(SPECIALIZATIONS),
        "levels": list(LEVELS),
        "types": list(TYPES),
        "competencies": COMPETENCIES,
        "competency_roles": {
            spec: {
                "mandatory": MANDATORY[spec],
                "key": KEY[spec],
                "critical": CRITICAL[spec],
            }
            for spec in SPECIALIZATIONS
        },
        "item_count": len(clean),
        "items": clean,
    }

    with open(os.path.join(dist_dir, "bank.json"), "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(json.dumps(bank_doc, ensure_ascii=False, indent=1))
        fh.write(chr(10))

    stats = compute_statistics(items)
    with open(os.path.join(dist_dir, "statistics.json"), "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(json.dumps(stats, ensure_ascii=False, indent=1))
        fh.write(chr(10))

    with open(os.path.join(dist_dir, "statistics.md"), "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(render_markdown(stats))

    print("dist/bank.json: %d заданий, %d форм" % (stats["total_items"], stats["total_rendered_forms"]))
    print("dist/statistics.json и dist/statistics.md обновлены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
