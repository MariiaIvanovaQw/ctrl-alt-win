"""
Проверка качества банка заданий.

Запуск:
    python tools/validate_bank.py            # все проверки
    python tools/validate_bank.py --json     # результат машиночитаемо

Коды выхода: 0 – ошибок нет, 1 – есть ошибки (ERROR).
Замечания уровня WARN не влияют на код выхода.

Состав проверок описан в docs/specification.md, раздел 8.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_lib import (
    LEVELS,
    SPECIALIZATIONS,
    TYPES,
    VALIDATION_TYPES,
    forms_of,
    level_for_difficulty,
    load_bank,
    render_item,
    score_for_difficulty,
)
from blueprint import BLUEPRINT, COMPETENCY_CAP, MANDATORY

ID_RE = re.compile(r"^(FE|BE|QA)-(J|M|S)-(T|S|P)-\d{3}$")
SPEC_CODE = {"FE": "frontend", "BE": "backend", "QA": "qa"}
LEVEL_CODE = {"J": "junior", "M": "middle", "S": "senior"}
TYPE_CODE = {"T": "theory", "S": "situational", "P": "practical"}

FORBIDDEN_OPTION_PATTERNS = [
    "все вышеперечисленное",
    "все перечисленное",
    "все варианты верны",
    "ничего из вышеперечисленного",
    "ни один из вариантов",
    "all of the above",
    "none of the above",
]

REQUIRED_FIELDS = (
    "id",
    "specialization",
    "level",
    "type",
    "competency",
    "difficulty",
    "question",
    "options",
    "correct_answer",
    "score",
    "explanation",
    "tags",
    "version_group",
    "seedable",
    "seed_parameters",
    "validation_type",
)

KNOWN_NORMALIZATION = {"trim", "lowercase", "uppercase", "remove_spaces", "collapse_whitespace"}

CHOICE_TYPES = {"single_choice", "multiple_choice"}


class Report:
    def __init__(self):
        self.entries = []

    def add(self, severity, check, message, item_id=None):
        self.entries.append(
            {"severity": severity, "check": check, "message": message, "item_id": item_id}
        )

    def error(self, check, message, item_id=None):
        self.add("ERROR", check, message, item_id)

    def warn(self, check, message, item_id=None):
        self.add("WARN", check, message, item_id)

    def info(self, check, message):
        self.add("INFO", check, message, None)

    @property
    def errors(self):
        return [e for e in self.entries if e["severity"] == "ERROR"]

    @property
    def warnings(self):
        return [e for e in self.entries if e["severity"] == "WARN"]


# ---------------------------------------------------------------- V1..V5

def check_structure(items, report):
    seen_ids = set()
    for item in items:
        iid = item.get("id", "<без id>")
        for field in REQUIRED_FIELDS:
            if field not in item:
                report.error("V1", "отсутствует поле %s" % field, iid)
        if not ID_RE.match(str(iid)):
            report.error("V1", "идентификатор не соответствует шаблону SPEC-LVL-TYPE-NNN", iid)
            continue
        if iid in seen_ids:
            report.error("V1", "повторяющийся идентификатор", iid)
        seen_ids.add(iid)

        spec, lvl, typ, _ = iid.split("-")
        if item.get("specialization") != SPEC_CODE[spec]:
            report.error("V1", "specialization не совпадает с префиксом идентификатора", iid)
        if item.get("level") != LEVEL_CODE[lvl]:
            report.error("V1", "level не совпадает с идентификатором", iid)
        if item.get("type") != TYPE_CODE[typ]:
            report.error("V1", "type не совпадает с идентификатором", iid)

        if item.get("specialization") not in SPECIALIZATIONS:
            report.error("V1", "недопустимая specialization", iid)
        if item.get("level") not in LEVELS:
            report.error("V1", "недопустимый level", iid)
        if item.get("type") not in TYPES:
            report.error("V1", "недопустимый type", iid)
        if item.get("validation_type") not in VALIDATION_TYPES:
            report.error("V1", "недопустимый validation_type", iid)

        difficulty = item.get("difficulty")
        if not isinstance(difficulty, int) or not 1 <= difficulty <= 10:
            report.error("V2", "difficulty должен быть целым 1..10", iid)
            continue
        if item.get("score") != score_for_difficulty(difficulty):
            report.error(
                "V2",
                "score=%r не соответствует difficulty=%d (ожидается %d)"
                % (item.get("score"), difficulty, score_for_difficulty(difficulty)),
                iid,
            )
        if level_for_difficulty(difficulty) != item.get("level"):
            report.error(
                "V2",
                "level=%s не соответствует difficulty=%d" % (item.get("level"), difficulty),
                iid,
            )

        if not str(item.get("question", "")).strip():
            report.error("V1", "пустой текст вопроса", iid)
        if not str(item.get("explanation", "")).strip():
            report.error("V1", "пустое объяснение", iid)
        if len(str(item.get("explanation", ""))) < 60:
            report.warn("V1", "слишком короткое объяснение", iid)
        for rule in item.get("answer_normalization") or []:
            if rule not in KNOWN_NORMALIZATION:
                report.error("V4", "неизвестное правило нормализации: %s" % rule, iid)
        if item.get("seedable") and not isinstance(item.get("seed_parameters"), list):
            report.error("V1", "seed_parameters должен быть массивом", iid)


def check_forms(items, report):
    for item in items:
        iid = item["id"]
        vtype = item.get("validation_type")
        variant_ids = set()
        forms = forms_of(item)
        base_is_choice = bool(forms[0]["options"])

        for form in forms:
            vid = form["variant_id"]
            if vid in variant_ids:
                report.error("V5", "повторяющийся variant_id %s" % vid, iid)
            variant_ids.add(vid)
            label = "%s/%s" % (iid, vid)
            options = form["options"]
            correct = form["correct_answer"]

            if bool(options) != base_is_choice:
                report.error("V5", "%s: формы различаются по наличию вариантов ответа" % label, iid)

            if vtype in CHOICE_TYPES:
                if len(options) != 4:
                    report.error("V3", "%s: ожидается ровно 4 варианта, найдено %d" % (label, len(options)), iid)
                ids = [o.get("id") for o in options]
                if ids != ["A", "B", "C", "D"]:
                    report.error("V3", "%s: идентификаторы вариантов должны быть A,B,C,D по порядку" % label, iid)
                texts = [str(o.get("text", "")).strip() for o in options]
                if any(not t for t in texts):
                    report.error("V3", "%s: есть пустой вариант ответа" % label, iid)
                if len(set(texts)) != len(texts):
                    report.error("V3", "%s: есть дублирующиеся варианты ответа" % label, iid)
                for text in texts:
                    low = text.lower()
                    for bad in FORBIDDEN_OPTION_PATTERNS:
                        if bad in low:
                            report.error("V3", "%s: запрещённая формулировка варианта (%s)" % (label, bad), iid)
                if vtype == "single_choice":
                    if len(correct) != 1:
                        report.error("V3", "%s: single_choice требует ровно один правильный ответ" % label, iid)
                else:
                    if len(correct) < 2:
                        report.error("V3", "%s: multiple_choice требует не менее двух правильных ответов" % label, iid)
                    if len(correct) >= 4:
                        report.error("V3", "%s: правильными не могут быть все варианты" % label, iid)
                if len(set(correct)) != len(correct):
                    report.error("V3", "%s: повторы в correct_answer" % label, iid)
                for letter in correct:
                    if letter not in ids:
                        report.error("V3", "%s: correct_answer ссылается на несуществующий вариант %s" % (label, letter), iid)
            else:
                if options:
                    report.error("V4", "%s: для %s варианты ответа не используются" % (label, vtype), iid)
                if not correct:
                    report.error("V4", "%s: пустой correct_answer" % label, iid)
                for value in correct:
                    if not str(value).strip():
                        report.error("V4", "%s: пустое эталонное значение" % label, iid)
                if vtype == "numeric":
                    for value in correct:
                        try:
                            float(str(value).replace(",", ".").strip())
                        except ValueError:
                            report.error("V4", "%s: numeric-ответ %r не разбирается как число" % (label, value), iid)
            if not str(form["question"]).strip():
                report.error("V1", "%s: пустой вопрос" % label, iid)


# ---------------------------------------------------------------- V6

def _normalize_text(text):
    text = str(text).lower()
    text = re.sub(r"[^0-9a-zа-яё]+", " ", text)
    return " ".join(text.split())


def _shingles(text, size=5):
    words = _normalize_text(text).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def check_duplicates(items, report):
    exact = defaultdict(list)
    for item in items:
        # у кодовых заданий формулировка вопроса намеренно одинаковая
        # ("что выведет код?"), поэтому ключом служит вопрос вместе с кодом
        key = _normalize_text(item["question"]) + "||" + _normalize_text(item.get("code") or "")
        exact[key].append(item["id"])
    for ids in exact.values():
        if len(ids) > 1:
            report.error("V6", "совпадающие формулировки вопроса: %s" % ", ".join(ids), ids[0])

    # приблизительные дубликаты внутри одной специализации
    by_spec = defaultdict(list)
    for item in items:
        by_spec[item["specialization"]].append(item)
    for group in by_spec.values():
        prepared = [(i["id"], _shingles(i["question"] + " " + i["explanation"])) for i in group]
        for a in range(len(prepared)):
            id_a, sh_a = prepared[a]
            if not sh_a:
                continue
            for b in range(a + 1, len(prepared)):
                id_b, sh_b = prepared[b]
                if not sh_b:
                    continue
                inter = len(sh_a & sh_b)
                if not inter:
                    continue
                jaccard = inter / float(len(sh_a | sh_b))
                if jaccard >= 0.60:
                    report.warn(
                        "V6",
                        "%s и %s похожи на %d%% (проверьте, не дубликат ли)"
                        % (id_a, id_b, round(jaccard * 100)),
                        id_a,
                    )


# ---------------------------------------------------------------- V7..V9

def check_distributions(items, report):
    forms_total = 0
    letters = Counter()
    letters_by_spec = defaultdict(Counter)
    for item in items:
        for form in forms_of(item):
            if form["options"] and item["validation_type"] == "single_choice":
                forms_total += 1
                letters[form["correct_answer"][0]] += 1
                letters_by_spec[item["specialization"]][form["correct_answer"][0]] += 1

    expected = forms_total / 4.0
    for letter in "ABCD":
        share = letters[letter] / float(forms_total) if forms_total else 0
        if abs(letters[letter] - expected) > max(5, 0.15 * expected):
            report.error(
                "V7",
                "перекос распределения правильных ответов: %s = %d из %d (%.1f%%)"
                % (letter, letters[letter], forms_total, share * 100),
            )
    report.info("V7", "распределение правильных ответов: %s" % dict(sorted(letters.items())))

    for spec, counter in sorted(letters_by_spec.items()):
        total = sum(counter.values())
        exp = total / 4.0
        for letter in "ABCD":
            if abs(counter[letter] - exp) > max(8, 0.25 * exp):
                report.warn(
                    "V7",
                    "%s: перекос по букве %s (%d из %d)" % (spec, letter, counter[letter], total),
                )

    for spec in SPECIALIZATIONS:
        spec_items = [i for i in items if i["specialization"] == spec]
        if len(spec_items) != 240:
            report.error("V8", "%s: %d заданий, ожидалось 240" % (spec, len(spec_items)))
        by_level = Counter(i["level"] for i in spec_items)
        by_type = Counter(i["type"] for i in spec_items)
        for level in LEVELS:
            if by_level[level] != 80:
                report.error("V8", "%s/%s: %d заданий, ожидалось 80" % (spec, level, by_level[level]))
        for typ in TYPES:
            if by_type[typ] != 80:
                report.error("V8", "%s/%s: %d заданий, ожидалось 80" % (spec, typ, by_type[typ]))

        comps = Counter(i["competency"] for i in spec_items)
        for competency, count in sorted(comps.items()):
            if count < 4:
                report.error(
                    "V8",
                    "%s: компетенция %s покрыта только %d заданиями (минимум 4)"
                    % (spec, competency, count),
                )
            elif count < 8:
                report.warn(
                    "V8", "%s: компетенция %s покрыта %d заданиями" % (spec, competency, count)
                )
            if count > 32:
                report.warn(
                    "V8", "%s: компетенция %s доминирует (%d заданий)" % (spec, competency, count)
                )
        # обязательная компетенция должна быть достижима хотя бы в одной
        # ячейке плана сборки каждого уровня, иначе покрытие не гарантировано
        for competency in MANDATORY[spec]:
            comp_items = [i for i in spec_items if i["competency"] == competency]
            for level in LEVELS:
                reachable = 0
                for typ, dmin, dmax, _count in BLUEPRINT[level]:
                    reachable += len(
                        [
                            i
                            for i in comp_items
                            if i["type"] == typ and dmin <= i["difficulty"] <= dmax
                        ]
                    )
                if reachable == 0:
                    report.error(
                        "V8",
                        "%s/%s: обязательная компетенция %s недостижима ни в одной ячейке плана"
                        % (spec, level, competency),
                    )
                elif reachable < 3:
                    report.warn(
                        "V8",
                        "%s/%s: обязательная компетенция %s достижима только через %d задани%s"
                        % (spec, level, competency, reachable, "е" if reachable == 1 else "я"),
                    )

        diffs = Counter(i["difficulty"] for i in spec_items)
        report.info(
            "V9", "%s: распределение difficulty %s" % (spec, dict(sorted(diffs.items())))
        )


# ---------------------------------------------------------------- V10

def check_version_groups(items, report):
    groups = defaultdict(list)
    for item in items:
        group = item.get("version_group")
        if group:
            groups[group].append(item)
    for group, members in sorted(groups.items()):
        comps = {m["competency"] for m in members}
        if len(comps) > 1:
            report.warn(
                "V10",
                "version_group %s объединяет разные компетенции: %s"
                % (group, ", ".join(sorted(comps))),
            )
        diffs = [m["difficulty"] for m in members]
        if max(diffs) - min(diffs) > 3:
            report.error(
                "V10",
                "version_group %s: разброс сложности %d..%d слишком велик"
                % (group, min(diffs), max(diffs)),
            )
        elif max(diffs) - min(diffs) > 2:
            report.warn(
                "V10",
                "version_group %s: разброс сложности %d..%d" % (group, min(diffs), max(diffs)),
            )
    # сопоставимость форм внутри одного задания
    for item in items:
        forms = forms_of(item)
        if len(forms) < 2:
            continue
        lengths = [len(str(f.get("code") or "")) for f in forms]
        if max(lengths) and min(lengths) and max(lengths) > 3 * max(1, min(lengths)):
            report.warn(
                "V10",
                "варианты задания сильно различаются по объёму кода (%d..%d символов)"
                % (min(lengths), max(lengths)),
                item["id"],
            )


# ---------------------------------------------------------------- V11

def check_seed_determinism(items, report, seeds=(1, 7, 184729, 2 ** 48 + 13)):
    by_id = {i["id"]: i for i in items}
    multi = [i for i in items if len(forms_of(i)) > 1]
    for item in items:
        for seed in seeds:
            first = render_item(item, seed)
            second = render_item(by_id[item["id"]], seed)
            if json.dumps(first, ensure_ascii=False, sort_keys=True) != json.dumps(
                second, ensure_ascii=False, sort_keys=True
            ):
                report.error("V11", "рендеринг не воспроизводится при одинаковом сиде", item["id"])
                break
    # проверка, что сид действительно меняет форму и порядок
    switched = 0
    for item in multi:
        seen = set()
        for seed in range(1, 60):
            payload, _ = render_item(item, seed)
            seen.add(payload["variant_id"])
        if len(seen) > 1:
            switched += 1
    if multi and switched < len(multi):
        report.error(
            "V11",
            "у %d заданий с вариантами сид не переключает вариант" % (len(multi) - switched),
        )
    reordered = 0
    choice_items = [i for i in items if i["validation_type"] == "single_choice"]
    for item in choice_items:
        letters = set()
        for seed in range(1, 40):
            _, key = render_item(item, seed)
            letters.add(key["correct_letters"][0])
        if len(letters) > 1:
            reordered += 1
    if choice_items and reordered < len(choice_items):
        report.error(
            "V11",
            "у %d заданий сид не меняет позицию правильного ответа"
            % (len(choice_items) - reordered),
        )
    # проверка правильности ключа: ответ по ключу всегда засчитывается
    from bank_lib import check_answer

    for item in items:
        for seed in (3, 99, 123456789):
            payload, key = render_item(item, seed)
            if payload["options"]:
                submitted = key["correct_letters"] if len(key["correct_letters"]) > 1 else key["correct_letters"][0]
            else:
                submitted = key["correct_values"][0]
            if not check_answer(key, submitted):
                report.error("V11", "эталонный ответ не проходит проверку", item["id"])
                break


# ---------------------------------------------------------------- V12

def check_blueprint_feasibility(items, report):
    from assemble_test import assemble_test

    pools = defaultdict(list)
    for item in items:
        pools[item["specialization"]].append(item)

    for spec in SPECIALIZATIONS:
        for level in LEVELS:
            # запас по каждой ячейке плана
            for typ, dmin, dmax, count in BLUEPRINT[level]:
                supply = [
                    i
                    for i in pools[spec]
                    if i["type"] == typ and dmin <= i["difficulty"] <= dmax
                ]
                if len(supply) < count:
                    report.error(
                        "V12",
                        "%s/%s: в ячейке (%s, d%d-%d) нужно %d заданий, в банке %d"
                        % (spec, level, typ, dmin, dmax, count, len(supply)),
                    )
                elif len(supply) < count * 3:
                    report.warn(
                        "V12",
                        "%s/%s: малый запас в ячейке (%s, d%d-%d): %d при потребности %d"
                        % (spec, level, typ, dmin, dmax, len(supply), count),
                    )
            # фактическая сборка на наборе сидов
            for seed in (1, 2, 3, 17, 184729, 999983):
                try:
                    test = assemble_test(pools[spec], spec, level, seed)
                except Exception as exc:
                    report.error(
                        "V12", "%s/%s seed=%s: сборка теста упала: %s" % (spec, level, seed, exc)
                    )
                    continue
                ids = [i["item_id"] for i in test["items"]]
                if len(set(ids)) != len(ids):
                    report.error("V12", "%s/%s seed=%s: в тесте повторяются задания" % (spec, level, seed))
                groups = [
                    g
                    for g in (i.get("version_group") for i in test["selected_raw"])
                    if g
                ]
                if len(set(groups)) != len(groups):
                    report.error(
                        "V12",
                        "%s/%s seed=%s: в тесте две задачи из одной version_group" % (spec, level, seed),
                    )
                comp_counts = Counter(i["competency"] for i in test["selected_raw"])
                if comp_counts and max(comp_counts.values()) > COMPETENCY_CAP:
                    report.error(
                        "V12",
                        "%s/%s seed=%s: превышен предел заданий на компетенцию (%d)"
                        % (spec, level, seed, max(comp_counts.values())),
                    )
                missing = [c for c in MANDATORY[spec] if comp_counts[c] == 0]
                if missing:
                    report.error(
                        "V12",
                        "%s/%s seed=%s: не покрыты обязательные компетенции: %s"
                        % (spec, level, seed, ", ".join(missing)),
                    )
                if len(comp_counts) < 8:
                    report.error(
                        "V12",
                        "%s/%s seed=%s: покрыто только %d компетенций (минимум 8)"
                        % (spec, level, seed, len(comp_counts)),
                    )


# ---------------------------------------------------------------- V13

# Пороги подсказки по длине. При четырёх вариантах случайный уровень для
# «самый длинный» и «самый короткий» равен 25 %; допускается отклонение до 35 %.
# Выделяющийся вариант (длиннее или короче ближайшего соседа в 1,8 раза и
# более) допустим лишь в единичных формах, иначе длина снова становится
# подсказкой. Эвристические атаки на собранные тесты проверяет S6 в
# tools/simulate_candidates.py.
LENGTH_RANK_SHARE_MAX = 0.35
LENGTH_OUTLIER_RATIO = 1.8
LENGTH_OUTLIER_SHARE_MAX = 0.05


def check_option_length_bias(items, report):
    considered = 0
    rank_counter = Counter()
    strong_long = 0
    strong_short = 0
    for item in items:
        if item["validation_type"] != "single_choice":
            continue
        for form in forms_of(item):
            if len(form["options"]) != 4 or len(form["correct_answer"]) != 1:
                continue
            lengths = {o["id"]: len(o["text"]) for o in form["options"]}
            if max(lengths.values()) <= 25:
                # короткие формы (числа, коды ответа) длиной не подсказывают
                continue
            considered += 1
            correct = form["correct_answer"][0]
            correct_len = lengths[correct]
            others = [v for k, v in lengths.items() if k != correct]
            rank = 1 + sum(1 for v in others if v > correct_len)
            rank_counter[rank] += 1
            if correct_len > LENGTH_OUTLIER_RATIO * max(others):
                strong_long += 1
            if min(others) > LENGTH_OUTLIER_RATIO * correct_len:
                strong_short += 1
    if not considered:
        return
    longest = rank_counter[1] / float(considered)
    shortest = rank_counter[4] / float(considered)
    report.info(
        "V13",
        "место правильного варианта по длине (1 – самый длинный): %s из %d форм"
        % (dict(sorted(rank_counter.items())), considered),
    )
    report.info(
        "V13",
        "правильный вариант самый длинный в %.1f%% форм, самый короткий – в %.1f%%; "
        "выделяется длиной в %d формах, краткостью – в %d"
        % (longest * 100, shortest * 100, strong_long, strong_short),
    )
    if longest > LENGTH_RANK_SHARE_MAX or shortest > LENGTH_RANK_SHARE_MAX:
        report.error(
            "V13",
            "подсказка по длине: самый длинный %.1f%%, самый короткий %.1f%% при пороге %.0f%%; "
            "список форм – python tools/length_bias_report.py"
            % (longest * 100, shortest * 100, LENGTH_RANK_SHARE_MAX * 100),
        )
    for name, value in (("длиной", strong_long), ("краткостью", strong_short)):
        if value / float(considered) > LENGTH_OUTLIER_SHARE_MAX:
            report.error(
                "V13",
                "правильный вариант выделяется %s в %d формах (%.1f%%), порог %.0f%%"
                % (name, value, 100.0 * value / considered, LENGTH_OUTLIER_SHARE_MAX * 100),
            )


# ---------------------------------------------------------------- main

def run(items):
    report = Report()
    check_structure(items, report)
    check_forms(items, report)
    check_duplicates(items, report)
    check_distributions(items, report)
    check_version_groups(items, report)
    check_seed_determinism(items, report)
    check_blueprint_feasibility(items, report)
    check_option_length_bias(items, report)
    return report


def main():
    items = load_bank()
    report = run(items)

    if "--json" in sys.argv:
        out = {
            "total_items": len(items),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "entries": report.entries,
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=1))
        sys.stdout.write("\n")
        return 1 if report.errors else 0

    print("заданий в банке: %d" % len(items))
    for severity in ("ERROR", "WARN", "INFO"):
        selected = [e for e in report.entries if e["severity"] == severity]
        if not selected:
            continue
        print("\n%s (%d):" % (severity, len(selected)))
        for entry in selected[:200]:
            prefix = "  [%s]" % entry["check"]
            if entry["item_id"]:
                print("%s %s: %s" % (prefix, entry["item_id"], entry["message"]))
            else:
                print("%s %s" % (prefix, entry["message"]))
        if len(selected) > 200:
            print("  ... ещё %d" % (len(selected) - 200))

    print(
        "\nитог: ошибок %d, предупреждений %d"
        % (len(report.errors), len(report.warnings))
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
