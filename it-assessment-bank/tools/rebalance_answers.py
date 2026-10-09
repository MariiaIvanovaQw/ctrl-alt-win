"""
Выравнивание распределения правильных ответов по буквам A/B/C/D в банке.

Зачем: хранимое распределение не должно иметь перекоса (это требование
к качеству банка, см. docs/specification.md, раздел 8, проверка V7). В рантайме
варианты ответа всё равно перемешиваются сидом, но перекос в самом банке
считается дефектом: он виден при экспорте и при отладке.

Как: скрипт переставляет тексты вариантов внутри задания и обновляет
correct_answer. Переставлять можно только те формы, в тексте которых нет
ссылок на буквы вариантов (например "в варианте B"), иначе объяснение
перестанет соответствовать разметке. Такие формы скрипт не трогает и
учитывает их буквы как фиксированные.

Запуск:  python tools/rebalance_answers.py [--apply]
Без --apply выполняется только расчёт и печать плана.
"""

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bank_lib import BANK_ROOT, Rng, forms_of

LETTERS = ("A", "B", "C", "D")

# Одиночная латинская заглавная A..D, не входящая в слово и не часть
# дефисного кода вроде "A-1". Именно такие вхождения означают ссылку
# на вариант ответа.
LETTER_REF = re.compile(r"(?<![\w\-])[ABCD](?![\w\-])")


def _texts_of_form(item, form):
    texts = [form["question"], form["explanation"]]
    for option in form["options"]:
        texts.append(option["text"])
    # объяснение базовой формы тоже может ссылаться на буквы
    texts.append(item["explanation"])
    texts.append(item["question"])
    return texts


def is_permutable(item, form):
    if len(form["options"]) != 4:
        return False
    if len(form["correct_answer"]) != 1:
        return False
    for text in _texts_of_form(item, form):
        if text and LETTER_REF.search(text):
            return False
    return True


def collect(items):
    """Возвращает список записей о каждой форме с вариантами ответа."""
    records = []
    for item in items:
        for index, form in enumerate(forms_of(item)):
            if not form["options"]:
                continue
            records.append(
                {
                    "item": item,
                    "form_index": index,  # 0 — базовая форма, иначе variants[index-1]
                    "letter": form["correct_answer"][0],
                    "permutable": is_permutable(item, form),
                }
            )
    return records


def plan(records):
    """Распределяет буквы по переставляемым формам так, чтобы итог был ровным."""
    fixed = Counter(r["letter"] for r in records if not r["permutable"])
    movable = [r for r in records if r["permutable"]]
    total = len(records)

    # целевое число на букву: как можно ровнее
    base, extra = divmod(total, len(LETTERS))
    target = {}
    for index, letter in enumerate(LETTERS):
        target[letter] = base + (1 if index < extra else 0)

    need = {letter: max(0, target[letter] - fixed[letter]) for letter in LETTERS}
    shortfall = len(movable) - sum(need.values())
    # если фиксированных букв где-то больше цели, остаток добираем по кругу
    order = sorted(LETTERS, key=lambda letter: (-need[letter], letter))
    i = 0
    while shortfall > 0:
        need[order[i % len(order)]] += 1
        shortfall -= 1
        i += 1
    while shortfall < 0:
        for letter in sorted(LETTERS, key=lambda letter: -need[letter]):
            if need[letter] > 0:
                need[letter] -= 1
                shortfall += 1
                break

    assignment = []
    for letter in LETTERS:
        assignment.extend([letter] * need[letter])
    # детерминированное распределение: стабильный порядок форм,
    # фиксированный сид раскладки
    rng = Rng(0x5EED_1234_ABCD_0001)
    assignment = rng.shuffled(assignment)
    return movable, assignment, fixed, target


def apply_plan(movable, assignment):
    changed = 0
    rng = Rng(0x5EED_1234_ABCD_0002)
    for record, letter in zip(movable, assignment):
        item = record["item"]
        if record["form_index"] == 0:
            container = item
        else:
            container = item["variants"][record["form_index"] - 1]
        options = container["options"]
        correct_old = container["correct_answer"][0]
        correct_text = None
        others = []
        for option in options:
            if option["id"] == correct_old:
                correct_text = option["text"]
            else:
                others.append(option["text"])
        if correct_text is None:
            raise AssertionError("не найден правильный вариант у %s" % item["id"])
        others = rng.shuffled(others)
        slots = list(LETTERS)
        target_index = slots.index(letter)
        new_texts = []
        other_iter = iter(others)
        for index in range(4):
            new_texts.append(correct_text if index == target_index else next(other_iter))
        container["options"] = [
            {"id": LETTERS[index], "text": new_texts[index]} for index in range(4)
        ]
        container["correct_answer"] = [letter]
        if letter != correct_old:
            changed += 1
    return changed


def main():
    apply_changes = "--apply" in sys.argv
    files = []
    for spec in sorted(os.listdir(BANK_ROOT)):
        spec_dir = os.path.join(BANK_ROOT, spec)
        if not os.path.isdir(spec_dir):
            continue
        for name in sorted(os.listdir(spec_dir)):
            if name.endswith(".json"):
                files.append(os.path.join(spec_dir, name))

    loaded = []
    all_items = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            chunk = json.load(fh)
        loaded.append((path, chunk))
        all_items.extend(chunk)

    # выравнивание выполняется отдельно по каждой специализации:
    # перекос внутри одной специализации так же нежелателен, как общий
    changed = 0
    for spec in ("frontend", "backend", "qa"):
        spec_items = [i for i in all_items if i["specialization"] == spec]
        records = collect(spec_items)
        movable, assignment, _fixed, target = plan(records)
        before = Counter(r["letter"] for r in records)
        print(
            "%-9s форм %3d, переставляемых %3d, фиксированных %2d"
            % (spec, len(records), len(movable), len(records) - len(movable))
        )
        print(
            "          было %s -> цель %s"
            % (dict(sorted(before.items())), dict(sorted(target.items())))
        )
        if apply_changes:
            changed += apply_plan(movable, assignment)

    if not apply_changes:
        print("")
        print("запуск без --apply: изменения не сохранены")
        return 0

    for path, chunk in loaded:
        with open(path, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(json.dumps(chunk, ensure_ascii=False, indent=1))
            fh.write(chr(10))

    print("")
    print("изменено форм: %d" % changed)
    for spec in ("frontend", "backend", "qa"):
        after = Counter()
        for item in [i for i in all_items if i["specialization"] == spec]:
            for form in forms_of(item):
                if form["options"]:
                    after[form["correct_answer"][0]] += 1
        print("%-9s стало %s" % (spec, dict(sorted(after.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
