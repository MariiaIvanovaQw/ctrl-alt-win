"""Кабинет кандидата: тестирование, категория и грейд."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.errors import errors
from app.models import Attempt, AttemptAnswer, CandidateProfile, CompetencyEstimate, GradeHistory
from app.reference import COMPETENCY_TITLES, SPECIALIZATIONS, track_title
from app.schemas import CompetencyRow, Level, Specialization
from app.security.deps import DB, CurrentCandidate
from app.services import assessment
from app.services.assessment import OUTCOME_TITLES
from app.services.cards import competency_rows

router = APIRouter(prefix="/api/v1/candidate/assessment", tags=["Кандидат: тестирование"], responses=errors(403))

CHECK_TITLES = {
    "overall_min": "Итоговый балл",
    "chance_margin_min": "Превышение уровня случайного угадывания",
    "easy_rate_min": "Доля баллов на базовых заданиях (d1–3)",
    "mid_rate_min": "Доля баллов на заданиях среднего уровня (d4–6)",
    "mid_plus_rate_min": "Доля баллов на заданиях d4–10",
    "mid_plus_solved_min": "Решено заданий d4–10",
    "hard_rate_min": "Доля баллов на сложных заданиях (d7–10)",
    "hard_solved_min": "Решено сложных заданий (d7–10)",
    "top_rate_min": "Доля баллов на самых сложных заданиях (d9–10)",
    "key_competencies": "Нет провалов по ключевым компетенциям",
    "critical_covered_min": "Измерено критических компетенций",
    "critical_avg_min": "Средний балл по критическим компетенциям",
}


class StartIn(BaseModel):
    specialization: Specialization
    level: Level = Field(description="Заявленный грейд, на который проходится тест")


class AnswerIn(BaseModel):
    value: str | int | float | list[str] | None = Field(
        description="Буква варианта, список букв, число или строка; null — очистить ответ"
    )


class SpecIn(BaseModel):
    specialization: Specialization


class ClientItem(BaseModel):
    position: int
    type: str
    validation_type: str = Field(description="single_choice | multiple_choice | numeric | exact_match")
    question: str
    language: str | None = None
    code: str | None = None
    options: list[dict]


class SignalIn(BaseModel):
    kind: Literal["focus_lost", "copy", "paste"] = Field(
        description="focus_lost — ушёл со вкладки теста; copy — скопировал текст задания; paste — вставил текст в ответ"
    )


class CheckOut(BaseModel):
    check: str
    title: str
    passed: bool
    detail: str


class AttemptResult(BaseModel):
    score: int
    points_earned: int
    points_possible: int
    chance_baseline: int
    outcome: str
    outcome_title: str
    evidence_level: str = Field(description="Уровень, подтверждённый правилами по фактам попытки")
    applied: dict = Field(description="Как результат изменил грейд: action, level, message")
    difficulty_buckets: dict
    competencies: list[dict]
    checks: dict[str, list[CheckOut]]
    finish_reason: str | None
    flags: list[dict] = Field(
        default_factory=list,
        description="Признаки для разбора: быстрые ответы, уход со вкладки, копирование. На грейд не влияют, "
                    "работодатель видит их в карточке",
    )


class AttemptOut(BaseModel):
    id: str
    specialization: str
    declared_level: str
    test_label: str
    status: str
    started_at: datetime
    deadline_at: datetime
    seconds_left: int
    items: list[ClientItem]
    answers: dict[int, str | int | float | list[str] | None]
    answered: int
    result: AttemptResult | None = None


class AttemptSummary(BaseModel):
    id: str
    specialization: str
    declared_level: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    score: int | None
    outcome: str | None
    evidence_level: str | None
    applied: dict | None


class AvailabilityOut(BaseModel):
    level: str
    allowed: bool
    reason: str | None = Field(None, description="survey_required | attempt_in_progress | retry_cooldown | failed_recently | grade_change_cooldown")
    message: str | None = None
    available_at: datetime | None = None


class GradeHistoryRow(BaseModel):
    from_level: str | None
    to_level: str
    reason: str
    at: datetime


class AssessmentStatusOut(BaseModel):
    specialization: str | None
    next_step: str = Field(description="survey | continue_attempt | decide_recommendation | take_test | done")
    message: str | None = None
    specialization_title: str | None = None
    direction_title: str | None = None
    track: str | None = None
    track_title: str | None = None
    industry: str | None = None
    self_level: str | None = None
    grade: dict | None = None
    recommendation: dict | None = None
    active_attempt: dict | None = None
    availability: list[AvailabilityOut] = Field(default_factory=list)
    competencies: list[CompetencyRow] = Field(default_factory=list)
    attempts: list["AttemptSummary"] = Field(default_factory=list)
    grade_history: list[GradeHistoryRow] = Field(default_factory=list)
    policy: dict | None = None


class AnswerSavedOut(BaseModel):
    position: int
    saved_at: datetime | None


class RecommendationAcceptedOut(BaseModel):
    action: str
    level: str


def _result(attempt: Attempt) -> AttemptResult | None:
    if attempt.status != "finished" or not attempt.result:
        return None
    doc = attempt.result
    decision = doc["grade_decision"]
    checks = {}
    for level, rows in decision.get("checks", {}).items():
        checks[level] = [
            CheckOut(check=r["check"], title=CHECK_TITLES.get(r["check"], r["check"]), passed=r["passed"], detail=r["detail"])
            for r in rows
        ]
    comps = [
        {
            "competency": c,
            "title": COMPETENCY_TITLES.get(c, c),
            "score": d["score"],
            "points_earned": d["points_earned"],
            "points_possible": d["points_possible"],
            "items": d["items"],
            "confidence": d["confidence"],
        }
        for c, d in sorted(doc["competency_details"].items(), key=lambda kv: -kv[1]["points_possible"])
    ]
    return AttemptResult(
        score=attempt.score,
        points_earned=attempt.points_earned,
        points_possible=attempt.points_possible,
        chance_baseline=decision["metrics"]["chance_baseline"],
        outcome=attempt.outcome,
        outcome_title=OUTCOME_TITLES.get(attempt.outcome, attempt.outcome),
        evidence_level=attempt.confirmed_level,
        applied=attempt.applied or {},
        difficulty_buckets=doc["difficulty_buckets"],
        competencies=comps,
        checks=checks,
        finish_reason=attempt.finish_reason,
        flags=[{"code": f.get("code"), "message": f.get("message")} for f in (attempt.flags or [])],
    )


def _attempt_out(db, attempt: Attempt) -> AttemptOut:
    answers = {
        a.position: (a.submitted or {}).get("value")
        for a in db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
    }
    left = max(0, int((attempt.deadline_at - utcnow()).total_seconds())) if attempt.status == "in_progress" else 0
    return AttemptOut(
        id=str(attempt.id),
        specialization=attempt.specialization,
        declared_level=attempt.declared_level,
        test_label=attempt.test_label,
        status=attempt.status,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        seconds_left=left,
        items=[ClientItem(**item) for item in attempt.client_items],
        answers=answers,
        answered=sum(1 for v in answers.values() if v is not None),
        result=_result(attempt),
    )


def _summary(a: Attempt) -> AttemptSummary:
    return AttemptSummary(
        id=str(a.id),
        specialization=a.specialization,
        declared_level=a.declared_level,
        status=a.status,
        started_at=a.started_at,
        finished_at=a.finished_at,
        score=a.score,
        outcome=a.outcome,
        evidence_level=a.confirmed_level,
        applied=a.applied,
    )


@router.get("/status", response_model=AssessmentStatusOut, summary="Категория, грейд и доступные попытки")
def status(user: CurrentCandidate, db: DB, specialization: Specialization | None = Query(None)):
    """
    Сводка для экрана «Категория и грейд»: текущий грейд, рекомендация (если
    тест показал уровень ниже заявленного), доступность теста каждого уровня
    с причиной и датой, история попыток и смен грейда, действующие правила.
    """
    settings = get_settings()
    profile = db.get(CandidateProfile, user.id)
    spec = specialization or (profile.primary_specialization if profile else None)
    if spec is None:
        survey = assessment.latest_survey(db, user.id)
        spec = survey.specialization if survey else None
    if spec is None:
        return {"specialization": None, "next_step": "survey", "message": "Пройдите опрос, чтобы выбрать специализацию"}
    grade = assessment.get_grade(db, user.id, spec)
    rec = assessment.open_recommendation(db, user.id, spec)
    active = assessment.active_attempt(db, user.id)
    survey = assessment.latest_survey(db, user.id, spec)
    estimates = {
        e.competency: e
        for e in db.scalars(select(CompetencyEstimate).where(CompetencyEstimate.user_id == user.id, CompetencyEstimate.specialization == spec))
    }
    # читаем до commit: commit возвращает соединение в пул, и недочитанный курсор
    # под нагрузкой оказывается на чужом или закрытом соединении
    history = list(db.scalars(
        select(GradeHistory).where(GradeHistory.user_id == user.id, GradeHistory.specialization == spec).order_by(GradeHistory.created_at)
    ))
    db.commit()
    if survey is None:
        next_step = "survey"
    elif active is not None:
        next_step = "continue_attempt"
    elif rec is not None:
        next_step = "decide_recommendation"
    elif grade is None:
        next_step = "take_test"
    else:
        next_step = "done"
    return {
        # отрасль в смысле ТЗ — IT-направление; специализация — трек внутри него
        "specialization": spec,
        "specialization_title": SPECIALIZATIONS[spec],
        "direction_title": SPECIALIZATIONS[spec],
        "track": survey.track if survey else None,
        "track_title": track_title(spec, survey.track) if survey else None,
        "industry": profile.industry if profile else None,
        "self_level": survey.self_level if survey else None,
        "next_step": next_step,
        "grade": None
        if grade is None
        else {"level": grade.level, "assigned_at": grade.assigned_at, "last_change_at": grade.last_change_at,
              "category": "%s · %s" % (SPECIALIZATIONS[spec], grade.level),
              # результат был выше уровня — следующий тест доступен без ожидания
              "promotion_offer": {"level": grade.promotion_level, "until": grade.promotion_until}
              if assessment.promotion_open(grade, grade.promotion_level or "")
              else None},
        "recommendation": None
        if rec is None
        else {"level": rec.recommended_level, "attempt_id": str(rec.attempt_id), "created_at": rec.created_at,
              "message": "Тест не подтвердил заявленный уровень. Вы можете принять уровень %s по результатам попытки "
                         "или пройти тест уровнем ниже — грейд не меняется без вашего решения." % rec.recommended_level},
        "active_attempt": None if active is None else {"id": str(active.id), "declared_level": active.declared_level, "deadline_at": active.deadline_at},
        "availability": assessment.availability_dicts(db, user, spec),
        "competencies": competency_rows(estimates),
        "attempts": [_summary(a) for a in assessment.finished_attempts(db, user.id, spec)],
        "grade_history": [
            {"from_level": h.from_level, "to_level": h.to_level, "reason": h.reason, "at": h.created_at} for h in history
        ],
        "policy": {
            "attempt_time_limit_minutes": settings.attempt_time_limit_minutes,
            "grade_change_cooldown_days": settings.grade_change_cooldown_days,
            "same_level_retry_days": settings.same_level_retry_days,
            "promotion_offer_days": settings.promotion_offer_days,
            "recommendation_clean_days": settings.recommendation_clean_days,
            "test_size": 26,
        },
    }


@router.post("/attempts", response_model=AttemptOut, status_code=201, responses=errors(409), summary="Начать тест")
def start(body: StartIn, user: CurrentCandidate, db: DB):
    """
    Собирает персональный тест: новый криптослучайный сид, из пяти вариантов
    выбирается наименее пересекающийся с прежними попытками. Кандидату
    уходят только тексты заданий и варианты, без идентификаторов, сложности
    и ключей. 409 — тест сейчас недоступен (причина и дата в details).
    """
    attempt = assessment.start_attempt(db, user, body.specialization, body.level)
    return _attempt_out(db, attempt)


@router.get("/attempts", response_model=list[AttemptSummary], summary="Мои попытки")
def list_attempts(user: CurrentCandidate, db: DB):
    rows = db.scalars(select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.started_at.desc()))
    return [_summary(a) for a in rows]


@router.get("/attempts/{attempt_id}", response_model=AttemptOut, responses=errors(404), summary="Попытка: задания, ответы, результат")
def get_attempt(attempt_id: uuid.UUID, user: CurrentCandidate, db: DB):
    attempt = assessment.get_owned_attempt(db, user, attempt_id)
    return _attempt_out(db, attempt)


@router.put("/attempts/{attempt_id}/answers/{position}", response_model=AnswerSavedOut, responses=errors(400, 404, 409),
            summary="Сохранить ответ на задание")
def answer(attempt_id: uuid.UUID, position: int, body: AnswerIn, user: CurrentCandidate, db: DB):
    row = assessment.save_answer(db, user, attempt_id, position, body.value)
    return {"position": row.position, "saved_at": row.answered_at}


@router.post("/attempts/{attempt_id}/signals", status_code=204, responses=errors(404),
             summary="Сигнал прокторинга: уход со вкладки, копирование")
def signal(attempt_id: uuid.UUID, body: SignalIn, user: CurrentCandidate, db: DB):
    """
    Браузер сообщает о событиях во время попытки. Кандидат предупреждён об
    этом на экране теста. Сигналы превращаются в признаки для разбора при
    завершении; грейд от них не зависит. После завершения попытки
    игнорируются.
    """
    assessment.record_signal(db, user, attempt_id, body.kind)
    return Response(status_code=204)


@router.post("/attempts/{attempt_id}/finish", response_model=AttemptOut, responses=errors(404),
             summary="Завершить тест и получить результат")
def finish(attempt_id: uuid.UUID, user: CurrentCandidate, db: DB):
    """
    Подсчёт баллов и определение грейда выполняются на сервере алгоритмами
    банка. Правильные ответы не раскрываются: по ним можно было бы собрать
    базу ответов. Кандидат видит баллы по компетенциям и полосам сложности
    и каждую проверку правил грейда с числами.
    """
    attempt = assessment.get_owned_attempt(db, user, attempt_id)
    if attempt.status == "in_progress":
        attempt = assessment.finish_attempt(db, attempt, "submitted")
    return _attempt_out(db, attempt)


@router.post("/recommendation/accept", response_model=RecommendationAcceptedOut, responses=errors(404, 409),
             summary="Принять рекомендованный уровень")
def accept_recommendation(body: SpecIn, user: CurrentCandidate, db: DB):
    return assessment.accept_recommendation(db, user, body.specialization)


@router.post("/recommendation/decline", status_code=204, responses=errors(404), summary="Отказаться от рекомендации")
def decline_recommendation(body: SpecIn, user: CurrentCandidate, db: DB):
    assessment.decline_recommendation(db, user, body.specialization)
    return Response(status_code=204)



AssessmentStatusOut.model_rebuild()
