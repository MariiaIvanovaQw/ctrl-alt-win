"""
Общая библиотека банка заданий.

Содержит:
  * загрузку банка из bank/<spec>/*.json;
  * детерминированный генератор псевдослучайных чисел SplitMix64
    (переносим между языками, см. docs/specification.md, раздел 4);
  * производные подпотоки по именованным доменам;
  * перестановку Фишера — Йетса;
  * рендеринг конкретной формы задания по сиду (выбор варианта,
    перестановка вариантов ответа, нормализация ответа);
  * проверку ответа кандидата.

Никаких внешних зависимостей и никаких обращений к сети.
Весь результат полностью воспроизводим при одинаковом сиде.
"""

import glob
import json
import os
import re

MASK64 = (1 << 64) - 1

SPECIALIZATIONS = ("frontend", "backend", "qa")
LEVELS = ("junior", "middle", "senior")
TYPES = ("theory", "situational", "practical")
VALIDATION_TYPES = (
    "single_choice",
    "multiple_choice",
    "numeric",
    "exact_match",
    "code_output",
)
OPTION_IDS = ("A", "B", "C", "D", "E", "F")

BANK_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bank")


# --------------------------------------------------------------------------
# Детерминированный ГПСЧ
# --------------------------------------------------------------------------

def splitmix64_next(state):
    """Один шаг SplitMix64. Возвращает (новое_состояние, значение)."""
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    z = (z ^ (z >> 31)) & MASK64
    return state, z


def fnv1a64(text):
    """FNV-1a 64 бита по UTF-8 представлению строки."""
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & MASK64
    return h


class Rng:
    """Поток случайных чисел на SplitMix64."""

    __slots__ = ("state",)

    def __init__(self, seed):
        self.state = seed & MASK64

    def next_u64(self):
        self.state, value = splitmix64_next(self.state)
        return value

    def below(self, n):
        """Равномерное целое в [0, n) без смещения (отбрасывание хвоста)."""
        if n <= 0:
            raise ValueError("n must be positive")
        if n == 1:
            return 0
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next_u64()
            if x < limit:
                return x % n

    def shuffled(self, items):
        """Перестановка Фишера — Йетса (сверху вниз), не меняет вход."""
        result = list(items)
        for i in range(len(result) - 1, 0, -1):
            j = self.below(i + 1)
            result[i], result[j] = result[j], result[i]
        return result


def sub_rng(seed, domain):
    """
    Независимый подпоток для именованного домена.

    Домен задаёт назначение потока, например:
      "pool:theory", "order", "options:FE-J-T-001", "variant:BE-M-P-003".
    Благодаря смешиванию сида с хешем домена подпотоки некоррелированы,
    а добавление нового домена не меняет уже существующие.
    """
    return Rng((seed ^ fnv1a64(domain)) & MASK64)


# --------------------------------------------------------------------------
# Загрузка банка
# --------------------------------------------------------------------------

def load_bank(bank_root=BANK_ROOT):
    """Читает все файлы банка и возвращает список заданий."""
    items = []
    pattern = os.path.join(bank_root, "*", "*.json")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as fh:
            chunk = json.load(fh)
        if not isinstance(chunk, list):
            raise ValueError("%s: ожидался массив заданий" % path)
        for item in chunk:
            item["_source_file"] = os.path.relpath(path, os.path.dirname(bank_root))
            items.append(item)
    return items


def load_dist_bank(path=None):
    """Читает собранный банк dist/bank.json."""
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist", "bank.json"
        )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["items"]


# --------------------------------------------------------------------------
# Формы задания (базовая форма + варианты)
# --------------------------------------------------------------------------

def forms_of(item):
    """
    Все конкретные формы задания.

    Форма v1 — базовые поля задания. Каждый элемент variants задаёт
    дополнительную форму и переопределяет code / options / correct_answer
    (и, если задано, question и explanation).
    Все формы проверяют одну и ту же компетенцию и имеют одинаковую сложность.
    """
    base = {
        "variant_id": "v1",
        "question": item["question"],
        "code": item.get("code"),
        "language": item.get("language"),
        "options": item.get("options") or [],
        "correct_answer": list(item["correct_answer"]),
        "explanation": item["explanation"],
    }
    forms = [base]
    for variant in item.get("variants") or []:
        forms.append(
            {
                "variant_id": variant["variant_id"],
                "question": variant.get("question", item["question"]),
                "code": variant.get("code", item.get("code")),
                "language": variant.get("language", item.get("language")),
                "options": variant.get("options") or [],
                "correct_answer": list(variant["correct_answer"]),
                "explanation": variant.get("explanation", item["explanation"]),
            }
        )
    return forms


def render_item(item, seed, position=0):
    """
    Готовит задание к показу кандидату.

    Детерминированно по (seed, item_id):
      * выбирает форму (вариант) задания;
      * перемешивает варианты ответа и переназначает им буквы A..D;
      * возвращает ключ проверки (set правильных букв либо эталонные строки).

    Возвращает кортеж (payload_для_клиента, answer_key_для_сервера).
    """
    item_id = item["id"]
    forms = forms_of(item)

    if len(forms) > 1 and item.get("seedable", True):
        idx = sub_rng(seed, "variant:%s" % item_id).below(len(forms))
    else:
        idx = 0
    form = forms[idx]

    payload = {
        "item_id": item_id,
        "variant_id": form["variant_id"],
        "position": position,
        "specialization": item["specialization"],
        "level": item["level"],
        "type": item["type"],
        "competency": item["competency"],
        "difficulty": item["difficulty"],
        "score": item["score"],
        "validation_type": item["validation_type"],
        "question": form["question"],
    }
    if form.get("language"):
        payload["language"] = form["language"]
    if form.get("code"):
        payload["code"] = form["code"]

    key = {
        "item_id": item_id,
        "variant_id": form["variant_id"],
        "validation_type": item["validation_type"],
        "score": item["score"],
        "competency": item["competency"],
        "difficulty": item["difficulty"],
        "answer_normalization": item.get("answer_normalization") or [],
    }

    options = form["options"]
    if options:
        shuffle = item.get("seedable", True) and "option_order" in (item.get("seed_parameters") or [])
        order = (
            sub_rng(seed, "options:%s:%s" % (item_id, form["variant_id"])).shuffled(options)
            if shuffle
            else list(options)
        )
        shown = []
        correct_letters = []
        for new_index, option in enumerate(order):
            letter = OPTION_IDS[new_index]
            shown.append({"id": letter, "text": option["text"]})
            if option["id"] in form["correct_answer"]:
                correct_letters.append(letter)
        payload["options"] = shown
        key["correct_letters"] = sorted(correct_letters)
        key["options_count"] = len(shown)
    else:
        payload["options"] = []
        key["correct_values"] = list(form["correct_answer"])
        key["options_count"] = 0

    key["explanation"] = form["explanation"]
    return payload, key


# Поля, которые кандидат видит во время попытки. Идентификатор задания,
# вариант, компетенция, уровень, сложность и вес остаются на сервере:
# по item_id удобно собирать общую базу ответов («BE-M-S-005 — ответ про
# агрегаты»), а сложность и вес подсказывают, какие задания «дороже».
# Ответ кандидат отправляет по номеру позиции в своей попытке.
CLIENT_FIELDS = ("position", "type", "validation_type", "question", "language", "code", "options")


def client_view(payload):
    """Представление задания для клиента: только то, что нужно для показа и ответа."""
    return {name: payload[name] for name in CLIENT_FIELDS if name in payload}


# --------------------------------------------------------------------------
# Проверка ответа
# --------------------------------------------------------------------------

_SPACES = re.compile(r"\s+")


def normalize_answer(value, rules):
    """Приводит введённый кандидатом текст к сравнимому виду."""
    text = "" if value is None else str(value)
    for rule in rules or []:
        if rule == "trim":
            text = text.strip()
        elif rule == "lowercase":
            text = text.lower()
        elif rule == "uppercase":
            text = text.upper()
        elif rule == "remove_spaces":
            text = _SPACES.sub("", text)
        elif rule == "collapse_whitespace":
            text = _SPACES.sub(" ", text).strip()
        else:
            raise ValueError("неизвестное правило нормализации: %s" % rule)
    return text


def _as_number(text):
    cleaned = text.strip().replace(",", ".").replace(" ", "")
    return float(cleaned)


def check_answer(key, submitted):
    """
    Проверяет ответ кандидата по ключу из render_item.

    submitted:
      single_choice   -> строка с буквой, например "B"
      multiple_choice -> список букв, например ["A", "C"]
      numeric         -> строка или число
      exact_match     -> строка
      code_output     -> строка

    Возвращает True/False. Никаких обращений к внешним сервисам.
    """
    vtype = key["validation_type"]

    if vtype in ("single_choice", "multiple_choice"):
        expected = set(key["correct_letters"])
        if submitted is None:
            return False
        if isinstance(submitted, (list, tuple, set)):
            given = {str(x).strip().upper() for x in submitted}
        else:
            given = {str(submitted).strip().upper()}
        if vtype == "single_choice" and len(given) != 1:
            return False
        return given == expected

    rules = key.get("answer_normalization") or ["trim"]
    expected_values = key["correct_values"]

    if vtype == "numeric":
        if submitted is None or str(submitted).strip() == "":
            return False
        try:
            got = _as_number(str(submitted))
        except ValueError:
            return False
        for expected in expected_values:
            try:
                if abs(got - _as_number(str(expected))) <= 1e-9:
                    return True
            except ValueError:
                continue
        return False

    given = normalize_answer(submitted, rules)
    for expected in expected_values:
        if given == normalize_answer(expected, rules):
            return True
    return False


# --------------------------------------------------------------------------
# Баллы
# --------------------------------------------------------------------------

def score_for_difficulty(difficulty):
    """Вес задания по его сложности (см. docs/specification.md, раздел 2)."""
    if 1 <= difficulty <= 3:
        return 1
    if 4 <= difficulty <= 6:
        return 2
    if 7 <= difficulty <= 8:
        return 3
    if 9 <= difficulty <= 10:
        return 4
    raise ValueError("difficulty вне диапазона 1..10: %r" % (difficulty,))


def level_for_difficulty(difficulty):
    if 1 <= difficulty <= 3:
        return "junior"
    if 4 <= difficulty <= 6:
        return "middle"
    if 7 <= difficulty <= 10:
        return "senior"
    raise ValueError("difficulty вне диапазона 1..10: %r" % (difficulty,))
