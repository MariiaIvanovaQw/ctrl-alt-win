"""
Сглаженные оценки компетенций кандидата.

В одной попытке на компетенцию приходится 1–4 задания, поэтому сырая доля
верных ответов шумная: одно задание даёт 0 % или 100 %. Оценка сжимается
к общему уровню кандидата пропорционально объёму данных (байесовское
сглаживание с априорным средним кандидата):

    estimate   = (earned + K · p0) / (possible + K)
    confidence = possible / (possible + K)

где earned и possible — баллы по компетенции во всех завершённых
попытках специализации (вес задания растёт со сложностью), p0 —
общая доля баллов кандидата в тех же попытках, K — «псевдобаллы»
априорного уровня. При K = 4 одно задание весом 2 сдвигает оценку
от среднего кандидата лишь на треть, а 12 баллов данных — на 75 %.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Attempt, CompetencyEstimate

PRIOR_POINTS = 4.0


def smooth(earned: float, possible: float, p0: float, k: float = PRIOR_POINTS) -> tuple[float, float]:
    estimate = (earned + k * p0) / (possible + k)
    confidence = possible / (possible + k)
    return estimate, confidence


def recompute(db: Session, user_id: uuid.UUID, specialization: str) -> dict[str, CompetencyEstimate]:
    attempts = db.scalars(
        select(Attempt).where(
            Attempt.user_id == user_id,
            Attempt.specialization == specialization,
            Attempt.status == "finished",
        )
    ).all()
    totals: dict[str, list[int]] = {}
    earned_all = possible_all = 0
    for attempt in attempts:
        details = (attempt.result or {}).get("competency_details") or {}
        for comp, d in details.items():
            row = totals.setdefault(comp, [0, 0, 0])
            row[0] += d["points_earned"]
            row[1] += d["points_possible"]
            row[2] += d["items"]
            earned_all += d["points_earned"]
            possible_all += d["points_possible"]
    db.execute(
        delete(CompetencyEstimate).where(
            CompetencyEstimate.user_id == user_id, CompetencyEstimate.specialization == specialization
        )
    )
    p0 = earned_all / possible_all if possible_all else 0.5
    result = {}
    for comp, (earned, possible, items) in totals.items():
        estimate, confidence = smooth(earned, possible, p0)
        row = CompetencyEstimate(
            user_id=user_id,
            specialization=specialization,
            competency=comp,
            earned=earned,
            possible=possible,
            items=items,
            raw_rate=round(earned / possible, 4) if possible else 0.0,
            estimate=round(estimate, 4),
            confidence=round(confidence, 4),
        )
        db.add(row)
        result[comp] = row
    return result


def confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "высокая"
    if confidence >= 0.5:
        return "средняя"
    return "низкая"
