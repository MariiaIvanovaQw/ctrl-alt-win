"""
Тестирование на платформе: правила доступа к попыткам, жизненный цикл
попытки и применение результата к грейду.

Алгоритмы банка дают оценку по фактам попытки (подтверждённый уровень и
полное обоснование). Как эта оценка меняет категорию, решают правила
платформы:

* грейд не понижается принудительно: результат ниже заявленного уровня
  становится рекомендацией, которую кандидат принимает сам, либо он
  проходит тест уровнем ниже;
* смена грейда — не чаще раза в grade_change_cooldown_days дней,
  кроме первичного распределения;
* повышение — только отдельным тестом более высокого уровня (уточнение
  постановщиков): если результат выше заявленного уровня, присваивается
  заявленный, а тест следующего уровня можно пройти сразу, без ожидания
  смены грейда, в течение promotion_offer_days дней;
* повтор того же уровня — не раньше same_level_retry_days дней;
* после неудачной попытки сразу доступны только уровни ниже (провал и
  уход ниже не «сжигают» попытку — уточнение постановщиков), а тот же
  уровень и выше — через same_level_retry_days дней: нельзя за один день
  пройти тесты всех уровней и увидеть втрое больше заданий банка;
* если кандидат сам пошёл на тест ниже своего грейда и не подтвердил
  даже его, грейд не понижается (ТЗ), но в карточке появляется признак
  для разбора `lower_test_failed`;
* одна активная попытка (уникальный индекс в БД), ограничение времени;
  брошенная попытка завершается по истечении времени с теми ответами,
  что успели дать.

* рекомендация уровня ниже заявленного выдаётся, только если в
  специализации не было неудачных попыток за recommendation_clean_days
  дней; иначе этот уровень подтверждается только тестом этого уровня.

Последнее правило закрывает «добор» грейда пересдачами. Угадывание на
тестах junior и middle почти никогда не подтверждает уровень, но на тесте
senior в ~2,7 % попыток даёт свидетельство junior/middle: заданий
d4–6 там мало, а угадывание на трудных заданиях (25 %) выше, чем у слабого
junior. С пересдачей раз в 30 дней это ~28 % за год; с правилом —
одна такая возможность (scripts/evaluate.py, раздел «пересдачи»).
"""

import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError, Conflict, NotFound
from app.models import (
    Attempt,
    AttemptAnswer,
    CandidateGrade,
    CandidateProfile,
    GradeHistory,
    GradeRecommendation,
    Survey,
    User,
)
from app.reference import LEVEL_INDEX, LEVELS, SPECIALIZATIONS
from app.services import competencies, integrity
from app.services.bank import bank

OUTCOME_TITLES = {
    "confirmed": "Заявленный уровень подтверждён",
    "promoted": "Результат выше заявленного уровня",
    "downgraded": "Результат ниже заявленного уровня",
}


@dataclass
class Availability:
    level: str
    allowed: bool
    reason: str | None = None
    message: str | None = None
    available_at: datetime | None = None


def latest_survey(db: Session, user_id: uuid.UUID, specialization: str | None = None) -> Survey | None:
    query = select(Survey).where(Survey.user_id == user_id)
    if specialization:
        query = query.where(Survey.specialization == specialization)
    return db.scalar(query.order_by(Survey.created_at.desc()))


def get_grade(db: Session, user_id: uuid.UUID, specialization: str) -> CandidateGrade | None:
    return db.scalar(
        select(CandidateGrade).where(CandidateGrade.user_id == user_id, CandidateGrade.specialization == specialization)
    )


def open_recommendation(db: Session, user_id: uuid.UUID, specialization: str) -> GradeRecommendation | None:
    return db.scalar(
        select(GradeRecommendation)
        .where(
            GradeRecommendation.user_id == user_id,
            GradeRecommendation.specialization == specialization,
            GradeRecommendation.resolved_at.is_(None),
        )
        .order_by(GradeRecommendation.created_at.desc())
    )


def active_attempt(db: Session, user_id: uuid.UUID) -> Attempt | None:
    attempt = db.scalar(select(Attempt).where(Attempt.user_id == user_id, Attempt.status == "in_progress"))
    if attempt is not None and utcnow() > attempt.deadline_at:
        finish_attempt(db, attempt, "expired")
        return None
    return attempt


def is_success(attempt: Attempt) -> bool:
    return LEVEL_INDEX.get(attempt.confirmed_level or "below_junior", 0) >= LEVEL_INDEX[attempt.declared_level]


def finished_attempts(db: Session, user_id: uuid.UUID, specialization: str) -> list[Attempt]:
    return list(
        db.scalars(
            select(Attempt)
            .where(Attempt.user_id == user_id, Attempt.specialization == specialization, Attempt.status == "finished")
            .order_by(Attempt.finished_at.desc())
        )
    )


def availability(db: Session, user: User, specialization: str) -> list[Availability]:
    settings = get_settings()
    now = utcnow()
    survey = latest_survey(db, user.id, specialization)
    active = active_attempt(db, user.id)
    grade = get_grade(db, user.id, specialization)
    finished = finished_attempts(db, user.id, specialization)
    last_failure = next((a for a in finished if not is_success(a)), None)
    failure_until = (
        last_failure.finished_at + timedelta(days=settings.same_level_retry_days) if last_failure is not None else None
    )
    result = []
    for level in LEVELS:
        if survey is None:
            result.append(Availability(level, False, "survey_required", "Сначала пройдите опрос по специализации"))
            continue
        if active is not None:
            result.append(Availability(level, False, "attempt_in_progress", "Сначала завершите начатую попытку"))
            continue
        last_same = next((a for a in finished if a.declared_level == level), None)
        if last_same is not None:
            retry_at = last_same.finished_at + timedelta(days=settings.same_level_retry_days)
            if now < retry_at:
                result.append(
                    Availability(
                        level,
                        False,
                        "retry_cooldown",
                        "Повторить тест того же уровня можно через %d дней после предыдущей попытки"
                        % settings.same_level_retry_days,
                        retry_at,
                    )
                )
                continue
        if (
            failure_until is not None
            and now < failure_until
            and LEVEL_INDEX[level] >= LEVEL_INDEX[last_failure.declared_level]
            and not (grade is not None and promotion_open(grade, level, now))
        ):
            result.append(
                Availability(
                    level,
                    False,
                    "failed_recently",
                    "После неудачной попытки сразу доступны только уровни ниже; этот уровень — через %d дней"
                    % settings.same_level_retry_days,
                    failure_until,
                )
            )
            continue
        if grade is not None and level != grade.level and not promotion_open(grade, level, now):
            change_at = grade.last_change_at + timedelta(days=settings.grade_change_cooldown_days)
            if now < change_at:
                result.append(
                    Availability(
                        level,
                        False,
                        "grade_change_cooldown",
                        "Грейд можно менять не чаще раза в %d дней" % settings.grade_change_cooldown_days,
                        change_at,
                    )
                )
                continue
        result.append(Availability(level, True))
    return result


# ------------------------------------------------------------------ попытка


def start_attempt(db: Session, user: User, specialization: str, level: str) -> Attempt:
    settings = get_settings()
    check = next(a for a in availability(db, user, specialization) if a.level == level)
    if not check.allowed:
        raise Conflict(
            check.message,
            code=check.reason,
            details={"available_at": check.available_at.isoformat() if check.available_at else None},
        )
    b = bank()
    previous = set(
        db.scalars(
            select(AttemptAnswer.item_id)
            .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
            .where(Attempt.user_id == user.id, Attempt.specialization == specialization)
        )
    )
    exposure = item_exposure(db, specialization)
    # Новый сид на каждую попытку; из нескольких кандидатов берётся тот,
    # что меньше всего пересекается с уже показанными этому кандидату
    # заданиями, а при равенстве — тот, чьи задания реже показывались всем
    # кандидатам (контроль показов: «засвеченные» задания выходят реже,
    # нагрузка на банк выравнивается).
    best = None
    for _ in range(max(1, settings.seed_candidates)):
        seed = secrets.randbits(63)
        if db.scalar(select(Attempt.id).where(Attempt.seed == seed)) is not None:
            continue
        test = b.assemble(specialization, level, seed)
        ids = {i["item_id"] for i in test["items"]}
        rank = (len(ids & previous), sum(exposure.get(i, 0) for i in ids))
        if best is None or rank < best[0]:
            best = (rank, seed, test)
    if best is None:  # pragma: no cover - вероятность совпадения 64-битных сидов ничтожна
        raise AppError("Не удалось подобрать вариант теста, повторите попытку", code="seed_exhausted")
    _rank, seed, test = best
    now = utcnow()
    attempt = Attempt(
        user_id=user.id,
        specialization=specialization,
        declared_level=level,
        seed=seed,
        bank_version=b.version,
        test_label=test["test_id"],
        started_at=now,
        deadline_at=now + timedelta(minutes=settings.attempt_time_limit_minutes),
        items=test["items"],
        keys=test["answer_keys"],
        client_items=test["client_items"],
    )
    db.add(attempt)
    try:
        db.flush()
    except IntegrityError as exc:  # два одновременных «Начать тест»: уникальный индекс пропустит один
        db.rollback()
        raise Conflict("Сначала завершите начатую попытку", code="attempt_in_progress") from exc
    for payload in test["items"]:
        db.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                position=payload["position"],
                item_id=payload["item_id"],
                variant_id=payload["variant_id"],
                competency=payload["competency"],
                difficulty=payload["difficulty"],
            )
        )
    db.commit()
    return attempt


def item_exposure(db: Session, specialization: str) -> dict[str, int]:
    """Сколько раз каждое задание специализации показывалось в попытках всех кандидатов."""
    return dict(
        db.execute(
            select(AttemptAnswer.item_id, func.count())
            .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
            .where(Attempt.specialization == specialization)
            .group_by(AttemptAnswer.item_id)
        ).all()
    )


def get_owned_attempt(db: Session, user: User, attempt_id: uuid.UUID) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise NotFound("Попытка не найдена")
    if attempt.status == "in_progress" and utcnow() > attempt.deadline_at:
        finish_attempt(db, attempt, "expired")
    return attempt


def _validate_answer(key: dict, client_item: dict, value):
    vtype = key["validation_type"]
    if value is None:
        return None
    if vtype == "single_choice":
        ids = {o["id"] for o in client_item.get("options", [])}
        if not isinstance(value, str) or value.strip().upper() not in ids:
            raise AppError("Выберите один из предложенных вариантов", code="invalid_answer")
        return value.strip().upper()
    if vtype == "multiple_choice":
        ids = {o["id"] for o in client_item.get("options", [])}
        if not isinstance(value, list) or not value or any(str(v).upper() not in ids for v in value):
            raise AppError("Выберите варианты из предложенных", code="invalid_answer")
        return sorted({str(v).upper() for v in value})
    if not isinstance(value, (str, int, float)) or len(str(value)) > 300:
        raise AppError("Ответ должен быть строкой не длиннее 300 символов", code="invalid_answer")
    return str(value)


def save_answer(db: Session, user: User, attempt_id: uuid.UUID, position: int, value) -> AttemptAnswer:
    attempt = get_owned_attempt(db, user, attempt_id)
    if attempt.status != "in_progress":
        code = "attempt_expired" if attempt.finish_reason == "expired" else "attempt_finished"
        raise Conflict("Попытка уже завершена", code=code)
    if not 0 <= position < len(attempt.keys):
        raise NotFound("Нет задания с таким номером")
    normalized = _validate_answer(attempt.keys[position], attempt.client_items[position], value)
    row = db.get(AttemptAnswer, (attempt.id, position))
    row.submitted = {"value": normalized} if normalized is not None else None
    row.answered_at = utcnow()
    db.commit()
    return row


SIGNAL_KINDS = ("focus_lost", "copy", "paste")
SIGNAL_CAP = 999


def record_signal(db: Session, user: User, attempt_id: uuid.UUID, kind: str) -> None:
    """
    Лёгкий прокторинг: браузер сообщает об уходе со вкладки и о копировании
    или вставке текста. Это признаки для разбора (защита от подсказок со
    стороны и от выноса заданий), на грейд они не влияют.
    """
    attempt = get_owned_attempt(db, user, attempt_id)
    if attempt.status != "in_progress":
        return
    signals = dict(attempt.signals or {})
    signals[kind] = min(SIGNAL_CAP, int(signals.get(kind, 0)) + 1)
    attempt.signals = signals
    db.commit()


def detect_flags(attempt: Attempt, answers: list[AttemptAnswer]) -> list[dict]:
    """Признаки для ручного разбора; на грейд не влияют."""
    flags = []
    if attempt.finish_reason == "demo_autofill":
        flags.append({"code": "demo_autofill", "message": "Демо-режим: часть ответов подставлена автоматически"})
    signals = attempt.signals or {}
    if signals.get("focus_lost", 0) >= 3:
        flags.append({"code": "focus_lost", "count": signals["focus_lost"],
                      "message": "Уходил со вкладки теста %d раз" % signals["focus_lost"]})
    if signals.get("copy", 0) or signals.get("paste", 0):
        flags.append({"code": "copy_paste", "copy": signals.get("copy", 0), "paste": signals.get("paste", 0),
                      "message": "Копирование текста заданий: %d, вставка в ответы: %d"
                                 % (signals.get("copy", 0), signals.get("paste", 0))})
    timed = sorted((a for a in answers if a.answered_at), key=lambda a: a.answered_at)
    fast_hard = 0
    previous = attempt.started_at
    for a in timed:
        if a.difficulty >= 7 and a.is_correct and (a.answered_at - previous).total_seconds() < 5:
            fast_hard += 1
        previous = a.answered_at
    if fast_hard >= 3:
        flags.append({"code": "fast_hard_answers", "count": fast_hard, "message": "Верные ответы на сложные задания быстрее 5 секунд"})
    if attempt.finished_at and attempt.score is not None:
        minutes = (attempt.finished_at - attempt.started_at).total_seconds() / 60
        if minutes < 5 and attempt.score >= 80:
            flags.append({"code": "very_fast_high_score", "minutes": round(minutes, 1), "message": "Высокий результат менее чем за 5 минут"})
    return flags


def result_summary(document: dict) -> dict:
    decision = document.get("grade_decision") or {}
    return {
        "difficulty_buckets": document.get("difficulty_buckets") or {},
        "grade_decision": {
            "outcome": decision.get("outcome"),
            "confirmed_level": decision.get("confirmed_level"),
            "metrics": decision.get("metrics"),
        },
    }


def finish_attempt(db: Session, attempt: Attempt, reason: str = "submitted") -> Attempt:
    if attempt.status == "finished":
        return attempt
    b = bank()
    answers = list(
        db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id).order_by(AttemptAnswer.position))
    )
    submitted = {a.item_id: a.submitted["value"] for a in answers if a.submitted}
    now = utcnow()
    test = {
        "test_id": attempt.test_label,
        "specialization": attempt.specialization,
        "declared_level": attempt.declared_level,
        "seed": attempt.seed,
        "blueprint": [list(cell) for cell in b.blueprint.BLUEPRINT[attempt.declared_level]],
        "items": attempt.items,
        "answer_keys": attempt.keys,
    }
    document = b.result_document(str(attempt.user_id), test, submitted, now.isoformat())
    by_item = {row["item_id"]: row for row in document["answers"]}
    for a in answers:
        a.is_correct = bool(by_item[a.item_id]["is_correct"])
        value = (a.submitted or {}).get("value")
        a.answer_key = integrity.canonical_answer(attempt.client_items[a.position], attempt.keys[a.position], value)
    attempt.result = document
    attempt.summary = result_summary(document)
    attempt.score = document["score"]
    attempt.points_earned = document["points_earned"]
    attempt.points_possible = document["points_possible"]
    attempt.confirmed_level = document["confirmed_level"]
    attempt.outcome = document["outcome"]
    attempt.status = "finished"
    attempt.finished_at = now
    attempt.finish_reason = reason
    attempt.flags = detect_flags(attempt, answers) + integrity.answer_overlap_flags(db, attempt, answers)
    db.flush()
    attempt.applied = apply_result(db, attempt)
    competencies.recompute(db, attempt.user_id, attempt.specialization)
    profile = db.get(CandidateProfile, attempt.user_id)
    if profile is not None:
        profile.last_active_at = now
    db.commit()
    from app.services.matching import reset_category_cache

    reset_category_cache()  # новая категория видна в статистике сразу, а не через TTL кэша
    return attempt


# ------------------------------------------------------------------ грейд


def _assign(db: Session, user_id: uuid.UUID, specialization: str, level: str, attempt_id, reason: str) -> None:
    now = utcnow()
    grade = get_grade(db, user_id, specialization)
    previous = grade.level if grade else None
    if grade is None:
        grade = CandidateGrade(user_id=user_id, specialization=specialization, level=level)
        db.add(grade)
    grade.level = level
    grade.defining_attempt_id = attempt_id
    grade.assigned_at = now
    if previous != level:
        grade.last_change_at = now
    db.add(
        GradeHistory(
            user_id=user_id,
            specialization=specialization,
            from_level=previous,
            to_level=level,
            reason=reason,
            attempt_id=attempt_id,
        )
    )
    profile = db.get(CandidateProfile, user_id)
    if profile is not None and not profile.primary_specialization:
        profile.primary_specialization = specialization


def _supersede_recommendations(db: Session, user_id: uuid.UUID, specialization: str) -> None:
    rec = open_recommendation(db, user_id, specialization)
    if rec is not None:
        rec.resolved_at = utcnow()
        rec.resolution = "superseded"


def recent_failure(db: Session, attempt: Attempt) -> bool:
    """Была ли за recommendation_clean_days другая неудачная попытка в специализации."""
    since = attempt.finished_at - timedelta(days=get_settings().recommendation_clean_days)
    earlier = db.scalars(
        select(Attempt).where(
            Attempt.user_id == attempt.user_id,
            Attempt.specialization == attempt.specialization,
            Attempt.status == "finished",
            Attempt.id != attempt.id,
            Attempt.finished_at >= since,
        )
    )
    return any(not is_success(a) for a in earlier)


def _lv(level: str) -> str:
    """Уровень для текста сообщения: «Middle», а не «middle»."""
    return level.capitalize()


def promotion_open(grade, level: str, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return bool(grade.promotion_level == level and grade.promotion_until and now < grade.promotion_until)


def _offer_promotion(db: Session, user_id: uuid.UUID, spec: str, level: str, applied: dict) -> dict:
    """Результат выше уровня: не автопрыжок, а право сразу пройти тест этого уровня."""
    db.flush()  # грейд мог быть только что создан в этой транзакции
    grade = get_grade(db, user_id, spec)
    grade.promotion_level = level
    grade.promotion_until = utcnow() + timedelta(days=get_settings().promotion_offer_days)
    applied["promotion_offer"] = {"level": level, "until": grade.promotion_until.isoformat()}
    applied["message"] += (
        ". Результат выше этого уровня: тест уровня %s можно пройти сразу, без ожидания смены грейда, "
        "в течение %d дней" % (_lv(level), get_settings().promotion_offer_days)
    )
    return applied


def apply_result(db: Session, attempt: Attempt) -> dict:
    """Как результат попытки меняет грейд (правила раздела 4.8)."""
    spec = attempt.specialization
    evidence = attempt.confirmed_level or "below_junior"
    declared = attempt.declared_level
    grade = get_grade(db, attempt.user_id, spec)
    current = grade.level if grade else None
    success = LEVEL_INDEX[evidence] >= LEVEL_INDEX[declared]
    _supersede_recommendations(db, attempt.user_id, spec)
    if grade is not None and grade.promotion_level == declared:
        grade.promotion_level = grade.promotion_until = None  # пропуск использован

    if success:
        # Присваивается заявленный уровень, даже если результат выше:
        # повышение подтверждается отдельным тестом (см. _offer_promotion).
        above = evidence if LEVEL_INDEX[evidence] > LEVEL_INDEX[declared] else None
        if grade is None:
            _assign(db, attempt.user_id, spec, declared, attempt.id, "initial")
            applied = {"action": "assigned", "level": declared, "message": "Категория присвоена: %s, %s" % (SPECIALIZATIONS[spec], _lv(declared))}
        elif LEVEL_INDEX[declared] > LEVEL_INDEX[current]:
            _assign(db, attempt.user_id, spec, declared, attempt.id, "promotion")
            applied = {"action": "promoted", "level": declared, "message": "Грейд повышен до %s" % _lv(declared)}
        elif LEVEL_INDEX[evidence] >= LEVEL_INDEX[current]:
            # тот же уровень или тест ниже с результатом не ниже текущего грейда
            grade.defining_attempt_id = attempt.id
            grade.assigned_at = utcnow()
            applied = {"action": "reconfirmed", "level": current, "message": "Грейд %s подтверждён повторно" % _lv(current)}
            above = evidence if LEVEL_INDEX[evidence] > LEVEL_INDEX[current] else None
        else:
            # кандидат сам выбрал тест уровнем ниже и прошёл его
            _assign(db, attempt.user_id, spec, declared, attempt.id, "lowered_by_choice")
            applied = {"action": "lowered_by_choice", "level": declared,
                       "message": "Грейд изменён на %s по вашему выбору" % _lv(declared)}
        if above:
            _offer_promotion(db, attempt.user_id, spec, above, applied)
        return applied

    if grade is None:
        if evidence != "below_junior" and recent_failure(db, attempt):
            return {
                "action": "verify_required",
                "level": evidence,
                "message": (
                    "Заявленный уровень %s не подтверждён. Результат указывает на уровень %s, но после "
                    "неудачных попыток его нужно подтвердить тестом уровня %s." % (_lv(declared), _lv(evidence), _lv(evidence))
                ),
            }
        if evidence != "below_junior":
            db.add(
                GradeRecommendation(
                    user_id=attempt.user_id, specialization=spec, recommended_level=evidence, attempt_id=attempt.id
                )
            )
            return {
                "action": "recommendation",
                "level": evidence,
                "message": (
                    "Заявленный уровень %s не подтверждён. По результатам попытки рекомендован уровень %s: "
                    "его можно принять сразу или пройти тест уровнем ниже." % (_lv(declared), _lv(evidence))
                ),
            }
        lower = LEVELS[LEVEL_INDEX[declared] - 2] if LEVEL_INDEX[declared] > 1 else None
        return {
            "action": "not_confirmed",
            "level": None,
            "message": "Уровень не подтверждён."
            + (" Можно сразу пройти тест уровня %s." % _lv(lower) if lower else " Повторить тест можно позже."),
        }

    applied = {
        "action": "kept",
        "level": current,
        "message": "Результат не повлиял на грейд: подтверждённый уровень %s сохраняется" % _lv(current),
    }
    if LEVEL_INDEX[declared] < LEVEL_INDEX[current]:
        # тест ниже собственного грейда не подтверждён: грейд не понижается
        # принудительно (ТЗ), но работодатель видит признак для разбора
        _flag_defining_attempt(db, grade, {
            "code": "lower_test_failed",
            "message": "Не подтвердил уровень %s на тесте ниже текущего грейда (%s)"
                       % (_lv(declared), attempt.finished_at.date().isoformat()),
        })
        applied["message"] += ". Тест ниже грейда не подтверждён — это видно работодателю как признак для разбора"
    if LEVEL_INDEX[evidence] > LEVEL_INDEX[current]:
        # тест выше не пройден, но результат выше текущего грейда — без автопрыжка
        _offer_promotion(db, attempt.user_id, spec, evidence, applied)
    return applied


def _flag_defining_attempt(db: Session, grade: CandidateGrade, flag: dict) -> None:
    """Признак в определяющей попытке грейда: его показывает карточка кандидата."""
    defining = db.get(Attempt, grade.defining_attempt_id) if grade.defining_attempt_id else None
    if defining is not None:
        defining.flags = list(defining.flags or []) + [flag]


def accept_recommendation(db: Session, user: User, specialization: str) -> dict:
    rec = open_recommendation(db, user.id, specialization)
    if rec is None:
        raise NotFound("Нет действующей рекомендации")
    if get_grade(db, user.id, specialization) is not None:
        raise Conflict("Грейд уже присвоен", code="grade_exists")
    _assign(db, user.id, specialization, rec.recommended_level, rec.attempt_id, "recommendation_accepted")
    rec.resolved_at = utcnow()
    rec.resolution = "accepted"
    db.commit()
    return {"action": "assigned", "level": rec.recommended_level}


def decline_recommendation(db: Session, user: User, specialization: str) -> None:
    rec = open_recommendation(db, user.id, specialization)
    if rec is None:
        raise NotFound("Нет действующей рекомендации")
    rec.resolved_at = utcnow()
    rec.resolution = "declined"
    db.commit()


def availability_dicts(db: Session, user: User, specialization: str) -> list[dict]:
    return [asdict(a) for a in availability(db, user, specialization)]
