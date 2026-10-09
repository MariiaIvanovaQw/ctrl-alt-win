"""
Антиплагиат: признаки списывания для ручного разбора. На грейд и оценку
они не влияют — это материал для человека, а не приговор.

1. **Совпадение ошибок в тесте.** Верные ответы у сильных кандидатов
   совпадают естественно, а одинаковые *неверные* — редкость, если люди
   решают сами. У двух попыток сравниваются общие задания, на которые оба
   ответили неверно. Вероятность совпадения на задании берётся из того,
   как часто кандидаты выбирают каждый неверный вариант (популярная
   «ловушка» совпадает часто, редкий вариант — нет):

       q_i = Σ_j p_ij²,   p_ij = (c_ij + 1) / (n_i + K_i)

   где c_ij — сколько раз выбран неверный ответ j, K_i — число неверных
   вариантов. Число совпадений при независимой работе распределено по
   Пуассону-биномиально с вероятностями q_i; признак ставится, если
   совпадений не меньше 4 и такое число случайно встречается реже, чем
   0,001 / (число проверенных пар) — поправка на множественные сравнения.
   Проверяются только пары, где общих ошибок не меньше 4: их число не
   зависит от того, совпали ли ответы, поэтому поправка корректна.
   Ответ сравнивается по тексту выбранного варианта, а не по букве:
   порядок вариантов у каждой попытки свой.

   Сильный кандидат ошибается редко, поэтому списывание у него
   подтверждается слабее: 7 одинаковых ошибок из 7 при популярных
   «ловушках» случайно встречаются примерно 1 раз из 500 — этого мало для
   признака. Совпадения верных ответов не учитываются: у двух сильных
   кандидатов они естественны.

2. **Сходство ответов «предложите подход».** Тексты сравниваются по
   совпадающим тройкам слов (шинглам): какая доля троек более короткого
   ответа встречается в другом. Порог — 60 % при не менее чем 8 тройках.
   Перефразирование так не ловится, дословное копирование с правками —
   да.
"""

import hashlib
import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attempt, AttemptAnswer, EmployerTask, TaskAssignment, User
from app.services.consents import audit

MIN_MATCHES = 4  # меньше совпадений — признак не ставится при любой вероятности
FAMILY_P = 1e-3  # допустимая доля ложных признаков на одну завершённую попытку
TEXT_SHINGLE = 3
TEXT_MIN_SHINGLES = 8
TEXT_THRESHOLD = 0.6


# ------------------------------------------------------------------ тест


def _normalize_free(value) -> str:
    text = re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))
    try:
        return format(float(text.replace(",", ".")), "g")
    except ValueError:
        return text


def canonical_answer(client_item: dict, key: dict, value) -> str | None:
    """Ответ в виде, не зависящем от перестановки вариантов: хеш текста выбранного варианта."""
    if value is None:
        return None
    if key.get("options_count"):
        texts = {o["id"]: o["text"] for o in client_item.get("options", [])}
        letters = value if isinstance(value, list) else [value]
        raw = "\x1f".join(sorted(texts.get(str(letter).upper(), "?") for letter in letters))
    else:
        raw = _normalize_free(value)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _tail(probabilities: list[float], at_least: int) -> float:
    """P(X ≥ at_least) для суммы независимых испытаний Бернулли (Пуассон-биномиальное)."""
    dist = [1.0]
    for p in probabilities:
        nxt = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nxt[k] += v * (1 - p)
            nxt[k + 1] += v * p
        dist = nxt
    return sum(dist[at_least:])


def _odds_text(p: float) -> str:
    if p < 1e-6:
        return "реже чем 1 раз на миллион"
    n = 1 / p
    for step in (1000, 100, 10, 1):
        if n >= step * 10:
            n = round(n / step) * step
            break
    return "примерно 1 раз на %s" % format(int(n), ",").replace(",", " ")


def answer_overlap_flags(db: Session, attempt: Attempt, answers: list[AttemptAnswer]) -> list[dict]:
    """
    Сравнивает неверные ответы завершаемой попытки с попытками других
    кандидатов. Признак ставится обеим попыткам; пара пишется в журнал
    аудита (кандидат и работодатель не видят, с кем совпадение).
    """
    wrong = {(a.item_id, a.variant_id): a for a in answers if a.answer_key and a.is_correct is False}
    if len(wrong) < MIN_MATCHES:
        return []
    rows = db.execute(
        select(AttemptAnswer.attempt_id, AttemptAnswer.item_id, AttemptAnswer.variant_id, AttemptAnswer.answer_key)
        .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
        .where(
            AttemptAnswer.item_id.in_({item for item, _ in wrong}),
            AttemptAnswer.is_correct.is_(False),
            AttemptAnswer.answer_key.is_not(None),
            Attempt.user_id != attempt.user_id,
            Attempt.status == "finished",
        )
    ).all()
    counts: dict = defaultdict(Counter)
    by_attempt: dict = defaultdict(list)
    for other_id, item, variant, key in rows:
        pair = (item, variant)
        if pair in wrong:
            counts[pair][key] += 1
            by_attempt[other_id].append((pair, key))
    if not by_attempt:
        return []

    q = {}
    for pair, a in wrong.items():
        c = counts[pair]
        c[a.answer_key] += 1  # своя попытка тоже в выборке: оценка осторожнее
        k = attempt.keys[a.position]
        distractors = k["options_count"] - len(k.get("correct_letters", [])) if k.get("options_count") else len(c) + 1
        categories = max(distractors, len(c))
        total = sum(c.values()) + categories
        seen = [(v + 1) / total for v in c.values()]
        unseen = (categories - len(c)) * (1 / total) ** 2
        q[pair] = min(0.999, sum(p * p for p in seen) + unseen)

    tested = {other_id: shared for other_id, shared in by_attempt.items() if len(shared) >= MIN_MATCHES}
    compared = len(tested)
    hits = []
    for other_id, shared in tested.items():
        matches = sum(1 for pair, key in shared if key == wrong[pair].answer_key)
        if matches < MIN_MATCHES:
            continue
        p = _tail([q[pair] for pair, _ in shared], matches)
        if p * compared <= FAMILY_P:
            hits.append((p, other_id, matches, len(shared)))
    if not hits:
        return []

    hits.sort()
    p, _, matches, shared = hits[0]
    message = (
        "Совпадение ошибок с попыткой другого кандидата: %d одинаковых неверных ответов из %d общих заданий, "
        "где оба ошиблись; при самостоятельной работе так совпадает %s" % (matches, shared, _odds_text(p))
    )
    if len(hits) > 1:
        message += "; похожих попыток: %d" % len(hits)
    for p_pair, other_id, m, n in hits:
        audit(db, None, "integrity.answer_overlap", "attempt", attempt.id,
              other_attempt=str(other_id), matches=m, shared=n, p=p_pair)
        other = db.get(Attempt, other_id)
        if other is not None:
            other.flags = list(other.flags or []) + [{
                "code": "answer_overlap",
                "matches": m,
                "shared": n,
                "message": "Совпадение ошибок с более поздней попыткой другого кандидата: %d одинаковых неверных "
                           "ответов из %d общих заданий; при самостоятельной работе так совпадает %s"
                           % (m, n, _odds_text(p_pair)),
            }]
    return [{"code": "answer_overlap", "matches": matches, "shared": shared, "message": message}]


# ------------------------------------------------------------------ регулярные задания


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))
    return {tuple(words[i:i + TEXT_SHINGLE]) for i in range(len(words) - TEXT_SHINGLE + 1)}


def text_overlap(a: str, b: str) -> float:
    """Доля троек слов более короткого текста, которые есть в другом; 0, если текст слишком короткий."""
    sa, sb = _shingles(a), _shingles(b)
    shorter = min(len(sa), len(sb))
    if shorter < TEXT_MIN_SHINGLES:
        return 0.0
    return len(sa & sb) / shorter


def check_approach_answer(db: Session, assignment: TaskAssignment, task: EmployerTask) -> None:
    """
    Сравнивает ответ «предложите подход» с ответами других кандидатов на то
    же задание. Работодатель видит оба ответа, поэтому в признаке указан
    кандидат, с чьим ответом совпадение.
    """
    text = (assignment.answer or {}).get("text") or ""
    best = None
    for other in db.scalars(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task.id,
            TaskAssignment.id != assignment.id,
            TaskAssignment.submitted_at.is_not(None),
        )
    ):
        share = text_overlap(text, (other.answer or {}).get("text") or "")
        if share >= TEXT_THRESHOLD and (best is None or share > best[0]):
            best = (share, other)
    if best is None:
        return
    share, other = best
    me = db.get(User, assignment.candidate_user_id)
    them = db.get(User, other.candidate_user_id)
    assignment.similarity = {"candidate_id": them.public_id, "share": round(share, 2)}
    if not other.similarity or other.similarity.get("share", 0) < share:
        other.similarity = {"candidate_id": me.public_id, "share": round(share, 2)}
    audit(db, None, "integrity.task_overlap", "task_assignment", assignment.id,
          other_assignment=str(other.id), share=round(share, 2))
