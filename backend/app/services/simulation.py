"""
Модель ответов синтетического кандидата.

Используется сидом демо-данных и демо-режимом жюри
(«дозаполнить попытку»). Вероятность верного ответа зависит от сложности
задания по профилю симулятора банка (`it-assessment-bank/tools/simulate_candidates.py`)
и, при необходимости, от сдвига по компетенции.
"""

import random

from app.services.bank import bank


def simulated_value(rng: random.Random, key: dict, correct: bool):
    """Значение ответа на задание по ключу: верное или заведомо неверное."""
    if "correct_letters" in key:
        letters = key["correct_letters"]
        if correct:
            return letters[0] if len(letters) == 1 else sorted(letters)
        wrong = [x for x in "ABCDEF"[: key["options_count"]] if x not in letters]
        return rng.choice(wrong)
    return key["correct_values"][0] if correct else "__wrong__"


def simulated_answers(rng: random.Random, profile_name: str, keys: list[dict], offsets: dict | None = None) -> dict:
    """Ответы по профилю: {item_id: значение}."""
    probabilities = bank().simulator().PROFILES[profile_name]
    offsets = offsets or {}
    answers = {}
    for key in keys:
        p = probabilities[key["difficulty"] - 1] + offsets.get(key["competency"], 0.0)
        correct = rng.random() < max(0.02, min(0.99, p))
        answers[key["item_id"]] = simulated_value(rng, key, correct)
    return answers
