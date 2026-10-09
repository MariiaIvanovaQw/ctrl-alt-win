"""
Демонстрационные данные.

Создаёт синтетических кандидатов, работодателей с вакансиями из
app/data/role_profiles.py, участников реестра ФСП и демо-учётные записи.
Кандидаты проходят тест через настоящие сервисы платформы: у каждого есть
скрытый «истинный» профиль (уровень и сила по компетенциям), ответы
моделируются по нему, а категорию присваивают алгоритмы банка и правила
платформы. Истинные профили сохраняются в data/seed_truth.json — по ним
scripts/evaluate.py проверяет качество категоризации и подбора.

Все люди, компании и достижения вымышлены.

Демо-учётные записи помечены is_demo: их нельзя удалить и сменить им
пароль, чтобы посетители стенда не ломали сценарий друг другу. Общий пароль
у кандидатов, работодателей и жюри; у модератора — свой, случайный: он есть
только в data/demo_accounts.json на сервере и не отдаётся по сети.

Запуск (из каталога backend):
    python -m scripts.seed_demo --reset
    python -m scripts.seed_demo --reset --per-spec 120 --seed 7
    python -m scripts.seed_demo --if-empty     # для контейнера: заполнить, только если база пустая
"""

import argparse
import json
import random
import secrets
import string
from datetime import date, timedelta
from types import SimpleNamespace

from email_validator import validate_email
from sqlalchemy import func, select

from app.config import get_settings
from app.data.role_profiles import DEMO_VACANCIES, ROLE_PROFILES
from app.db import Base, SessionLocal, create_schema, engine, utcnow
from app.models import (
    Attempt,
    AttemptAnswer,
    CandidateGrade,
    CandidateProfile,
    Company,
    EmployerTask,
    FspAchievement,
    FspLink,
    GradeHistory,
    GuardianConsent,
    Need,
    Survey,
    TaskAssignment,
    User,
)
from app.reference import SKILLS
from app.security.passwords import hash_password
from app.security.tokens import hash_token
from app.services import assessment, competencies
from app.services.bank import bank
from app.services.consents import set_consent
from app.services.needs import build_need_profile
from app.services.simulation import simulated_answers

DEMO_PASSWORD = "Demo12345"
LEVELS = ("junior", "middle", "senior")

MALE = ["Алексей", "Дмитрий", "Иван", "Максим", "Артём", "Никита", "Егор", "Кирилл", "Михаил", "Андрей", "Павел", "Роман", "Сергей", "Тимур", "Глеб"]
FEMALE = ["Анна", "Мария", "Екатерина", "Дарья", "Полина", "Алина", "Виктория", "Софья", "Ксения", "Елизавета", "Наталья", "Ольга", "Юлия", "Вера"]
LAST = ["Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев",
        "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов", "Николаев", "Орлов", "Андреев", "Макаров", "Никитин", "Захаров"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород", "Томск", "Иннополис", "Самара", "Краснодар"]
EXTRA_STACK = {
    "backend": ["python", "java", "go", "postgresql", "mysql", "redis", "kafka", "rabbitmq", "docker", "kubernetes", "fastapi", "django",
                "spring", "grpc", "rest", "microservices", "oauth", "clickhouse", "elasticsearch", "linux", "ci_cd", "git", "highload"],
    "frontend": ["javascript", "typescript", "react", "nextjs", "vue", "redux", "mobx", "html", "css", "webpack", "jest", "playwright",
                 "storybook", "accessibility", "web_performance", "graphql", "rest", "git"],
    "qa": ["test_design", "test_cases", "bug_tracking", "postman", "sql", "api_testing", "playwright", "selenium", "pytest", "allure",
           "load_testing", "testrail", "mobile_testing", "devtools", "ci_cd", "python", "java", "docker"],
}
SALARY = {"junior": (70_000, 140_000), "middle": (160_000, 290_000), "senior": (280_000, 480_000)}
EXPERIENCE = {"junior": (0.3, 2.0), "middle": (2.0, 5.0), "senior": (5.0, 12.0)}
STRENGTH = {"weak": -0.10, "solid": 0.0, "strong": 0.08}
PROFILE_BY = {
    ("junior", "weak"): "weak_junior", ("junior", "solid"): "solid_junior", ("junior", "strong"): "strong_junior",
    ("middle", "weak"): "weak_middle", ("middle", "solid"): "solid_middle", ("middle", "strong"): "strong_middle",
    ("senior", "weak"): "weak_senior", ("senior", "solid"): "solid_senior", ("senior", "strong"): "solid_senior",
}
EVENT_LEVEL_WORD = {"international": "Международные", "federal": "Всероссийские", "regional": "Региональные", "local": "Межвузовские"}
EVENT_TOPIC = {
    "product": "продуктовому программированию",
    "algorithmic": "алгоритмическому программированию",
    "security": "программированию систем информационной безопасности",
}
COMPANIES = [
    {"name": "ПэйТех Лаб", "industry": "fintech", "city": "Москва", "description": "Платёжные сервисы для маркетплейсов."},
    {"name": "Северный маркет", "industry": "ecommerce", "city": "Санкт-Петербург", "description": "Интернет-магазин электроники и бытовой техники."},
    {"name": "Цифровые регионы", "industry": "gov", "city": "Казань", "description": "Цифровые сервисы для жителей регионов."},
]


# Метка «Компания проверена»: первая проверена, вторая ждёт решения модератора.
VERIFICATION = ["verified", "requested", "none"]


def demo_inn(n: int) -> str:
    """ИНН с верной контрольной суммой и несуществующим кодом региона 00 — не совпадёт с настоящей организацией."""
    base = [int(x) for x in "0000%05d" % n]
    check = sum(w * x for w, x in zip([2, 4, 10, 3, 5, 9, 4, 6, 8], base, strict=True)) % 11 % 10
    return "".join(map(str, base)) + str(check)


def person(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return "%s %s" % (rng.choice(LAST), rng.choice(MALE))
    last = rng.choice(LAST)
    return "%s %s" % (last + "а" if last.endswith(("ов", "ев", "ин")) else last, rng.choice(FEMALE))


TRACK_BY_SKILL = {
    "backend": [("python", "python"), ("java", "java"), ("go", "go"), ("nodejs", "nodejs"), ("php", "php")],
    "frontend": [("react", "react"), ("vue", "vue"), ("angular", "angular")],
}


def pick_track(rng: random.Random, spec: str, stack: list[str], roles: list[str]) -> str:
    """Специализация внутри направления — по стеку, как её выбрал бы сам кандидат."""
    if spec == "qa":
        return "automation" if "qa_automation" in roles else rng.choice(["manual", "manual", "mobile", "performance"])
    for skill, track in TRACK_BY_SKILL[spec]:
        if skill in stack:
            return track
    return "vanilla" if spec == "frontend" else rng.choice(["python", "java", "go"])


def moderator_password() -> str:
    """Случайный пароль модератора: буквы и цифры, проходит требования к паролю."""
    alphabet = string.ascii_letters + string.digits
    return "Mod-" + "".join(secrets.choice(alphabet) for _ in range(10)) + "7"


def make_user(db, email: str, role: str, password: str = DEMO_PASSWORD) -> User:
    # та же проверка, что у формы входа: адрес, который она отвергнет
    # (например, домен .local), не годится для демо-учётной записи
    validate_email(email, check_deliverability=False)
    user = User(email=email, role=role, password_hash=hash_password(password), email_verified=True, is_demo=True)
    db.add(user)
    db.flush()
    set_consent(db, user.id, "pd_processing", True)
    return user


def answer_as(rng: random.Random, profile_name: str, offsets: dict, attempt: Attempt) -> dict:
    """Ответы по истинному профилю: вероятность по сложности + сдвиг компетенции."""
    return simulated_answers(rng, profile_name, attempt.keys, offsets)


def take_test(db, rng, user: User, spec: str, level: str, profile_name: str, offsets: dict, days_ago: float) -> Attempt:
    attempt = assessment.start_attempt(db, user, spec, level)
    answers = answer_as(rng, profile_name, offsets, attempt)
    now = utcnow()
    for row in db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)):
        row.submitted = {"value": answers[row.item_id]}
        row.answered_at = now
    db.flush()
    attempt = assessment.finish_attempt(db, attempt, "submitted")
    # переносим попытку в прошлое, чтобы история выглядела реалистично
    shift = timedelta(days=days_ago)
    duration = timedelta(minutes=rng.randint(22, 55))
    attempt.started_at = now - shift
    attempt.finished_at = attempt.started_at + duration
    attempt.deadline_at = attempt.started_at + timedelta(minutes=60)
    # ответы распределены по времени попытки, как у живого кандидата;
    # признаки скорости пересчитываются по этим отметкам
    rows = list(db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id).order_by(AttemptAnswer.position)))
    step = duration / max(1, len(rows))
    for i, row in enumerate(rows):
        row.answered_at = attempt.started_at + step * (i + 1)
    kept = [f for f in (attempt.flags or []) if f.get("code") == "answer_overlap"]
    attempt.flags = assessment.detect_flags(attempt, rows) + kept
    grade = assessment.get_grade(db, user.id, spec)
    if grade is not None and grade.defining_attempt_id == attempt.id:
        grade.assigned_at = attempt.finished_at
        grade.last_change_at = attempt.finished_at
        for h in db.scalars(select(GradeHistory).where(GradeHistory.attempt_id == attempt.id)):
            h.created_at = attempt.finished_at
    db.commit()
    return attempt


def showcase_copied_attempt(db, rng: random.Random, accounts: dict) -> None:
    """
    Демонстрация антиплагиата: кандидат получает тот же тест, что у
    другого, и повторяет его ответы. Грейд считается как обычно, а в
    карточке у обоих появляется признак «совпадение ошибок».
    """
    # исходная попытка с подтверждённым уровнем и заметным числом ошибок:
    # у сильного кандидата ошибок мало, и совпадение было бы слабым свидетельством
    errors = (
        select(AttemptAnswer.attempt_id, func.count().label("wrong"))
        .where(AttemptAnswer.is_correct.is_(False))
        .group_by(AttemptAnswer.attempt_id)
        .subquery()
    )
    source = db.scalar(
        select(Attempt).join(errors, errors.c.attempt_id == Attempt.id)
        .where(Attempt.status == "finished", Attempt.specialization == "backend", Attempt.outcome == "confirmed")
        .order_by(errors.c.wrong.desc(), Attempt.finished_at)
        .limit(1)
    )
    if source is None:
        return
    user = make_user(db, "backend.copy@demo-fsp.ru", "candidate")
    original = db.get(CandidateProfile, source.user_id)
    profile = CandidateProfile(
        user_id=user.id, full_name=person(rng), city=original.city, contact_email=user.email,
        about="Разработчик направления backend.", experience_years=original.experience_years,
        stack=original.stack, work_formats=original.work_formats, salary_expectation=original.salary_expectation,
        roles=original.roles, open_to_offers=True, primary_specialization="backend",
        primary_track=original.primary_track, birth_date=original.birth_date,
        privacy={"show_full_name": False, "show_city": True, "show_about": True, "show_fsp": True, "show_experience": True},
    )
    db.add(profile)
    set_consent(db, user.id, "profile_publication", True)
    db.add(Survey(user_id=user.id, specialization="backend", track=original.primary_track, self_level="middle",
                  experience_years=original.experience_years, stack=original.stack, roles=original.roles,
                  work_formats=original.work_formats))
    db.commit()

    level = source.declared_level
    survey = db.scalar(select(Survey).where(Survey.user_id == user.id))
    survey.self_level = level
    db.commit()
    attempt = assessment.start_attempt(db, user, "backend", level)
    attempt.items, attempt.keys, attempt.client_items = source.items, source.keys, source.client_items
    given = {a.position: a for a in db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == source.id))}
    started = source.finished_at + timedelta(days=2)
    duration = timedelta(minutes=rng.randint(25, 45))
    rows = list(db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id).order_by(AttemptAnswer.position)))
    for i, row in enumerate(rows):
        src = given[row.position]
        row.item_id, row.variant_id, row.competency, row.difficulty = src.item_id, src.variant_id, src.competency, src.difficulty
        row.submitted = src.submitted
        row.answered_at = started + duration / len(rows) * (i + 1)
    db.flush()
    attempt = assessment.finish_attempt(db, attempt, "submitted")
    attempt.started_at, attempt.finished_at = started, started + duration
    attempt.deadline_at = started + timedelta(minutes=60)
    kept = [f for f in (attempt.flags or []) if f.get("code") == "answer_overlap"]
    attempt.flags = assessment.detect_flags(attempt, rows) + kept
    grade = assessment.get_grade(db, user.id, "backend")
    if grade is not None:
        grade.assigned_at = grade.last_change_at = attempt.finished_at
    profile.last_active_at = attempt.finished_at
    competencies.recompute(db, user.id, "backend")
    db.commit()
    accounts["showcase"] = {
        "antiplagiarism": {
            "candidate_id": user.public_id,
            "copied_from": db.get(User, source.user_id).public_id,
            "note": "Пример антиплагиата: этот кандидат повторил тест и ответы другого. Откройте карточку под "
                    "работодателем — в блоке «Результат теста» признак совпадения ошибок",
        }
    }


def showcase_minor(db, rng: random.Random, accounts: dict, company) -> None:
    """
    Демонстрация правил для несовершеннолетних: школьник 16 лет с согласием
    законного представителя и стажировка с отметкой «подходит для
    несовершеннолетних (15–17 лет)».
    """
    today = utcnow().date()
    internship = Need(
        company_id=company.id, title="Стажёр-фронтенд на летние каникулы", specialization="frontend", level="junior",
        description="Вёрстка лендингов и простые компоненты на React под присмотром наставника. "
                    "Удалённо, 4 часа в день, без ночных и сверхурочных работ.",
        team_description="Команда маркетинговых страниц, наставник — senior frontend",
        stack=["react", "html", "css", "javascript"], work_format="remote", city=None,
        salary_from=30000, salary_to=45000, is_published=True, suitable_for_minors=True,
        published_at=utcnow() - timedelta(days=3),
    )
    internship.profile = build_need_profile("frontend", "junior", internship.stack, internship.description,
                                            internship.team_description)
    db.add(internship)

    user = make_user(db, "student16@demo-fsp.ru", "candidate")
    profile = CandidateProfile(
        user_id=user.id, full_name="Тимур Ахметов", city="Казань", contact_email=user.email,
        birth_date=today - timedelta(days=int(16.3 * 365.25)),
        about="Школьник, участник соревнований по продуктовому программированию. Ищу стажировку на лето.",
        experience_years=0.5, stack=["react", "javascript", "html", "css"], work_formats=["remote"],
        salary_expectation=35000, roles=["developer"], open_to_offers=True,
        primary_specialization="frontend", primary_track="react",
        privacy={"show_full_name": False, "show_city": True, "show_about": True, "show_fsp": True, "show_experience": True},
    )
    db.add(profile)
    db.add(GuardianConsent(
        user_id=user.id, guardian_name="Ахметова Гульнара Рашидовна", guardian_email="parent16@demo-fsp.ru",
        status="granted", token_hash=hash_token("demo-guardian-%s" % user.id), requested_at=utcnow() - timedelta(days=5),
        expires_at=utcnow() + timedelta(days=9), decided_at=utcnow() - timedelta(days=4),
    ))
    set_consent(db, user.id, "profile_publication", True)
    db.add(Survey(user_id=user.id, specialization="frontend", track="react", self_level="junior", experience_years=0.5,
                  stack=profile.stack, roles=profile.roles, work_formats=profile.work_formats))
    db.commit()
    take_test(db, rng, user, "frontend", "junior", "strong_junior", {}, 20)
    competencies.recompute(db, user.id, "frontend")
    db.commit()
    accounts["showcase"] = {**accounts.get("showcase", {}), "minor": {
        "email": user.email,
        "candidate_id": user.public_id,
        "note": "Кандидат 16 лет с согласием законного представителя. Работодатель видит отметку «до 18 лет»; "
                "пригласить можно только с отметкой «подходит для несовершеннолетних (15–17 лет)». Для него есть вакансия "
                "«Стажёр-фронтенд на летние каникулы»",
    }}


def fsp_participant(rng: random.Random, fsp_id: str, name: str, spec: str, true_level: str, strength: str, city: str,
                    email: str | None = None) -> dict:
    """
    Участник реестра ФСП. Допущение модели: число и уровень достижений
    растут с истинной силой участника (уровнем и «силой» внутри уровня);
    это допущение указано в отчёте валидации.
    """
    skill = LEVELS.index(true_level) / 2 + {"weak": -0.4, "solid": 0.0, "strong": 0.6}[strength]
    disciplines = {"backend": ["product", "algorithmic", "security"], "frontend": ["product", "algorithmic"], "qa": ["product", "security"]}[spec]
    count = rng.choices([0, 1, 2, 3], weights=[max(0.3, 2 - skill), 4, 2 + skill, max(0.1, 1 + 2 * skill)])[0]
    items = []
    for i in range(count):
        discipline = rng.choice(disciplines)
        level = rng.choices(["international", "federal", "regional", "local"], weights=[1, 4, 5, 3])[0]
        result = rng.choices(["winner", "prize", "finalist", "participant"],
                             weights=[max(0.1, 0.5 + 2 * skill), 2 + 2 * skill, 3, max(0.5, 7 - 4 * skill)])[0]
        when = date(2026, 9, 1) - timedelta(days=rng.randint(30, 1500))
        items.append(
            {
                "id": "%s-%d" % (fsp_id, i + 1),
                "event_name": "%s соревнования по %s" % (EVENT_LEVEL_WORD[level], EVENT_TOPIC[discipline]),
                "discipline": discipline,
                "event_level": level,
                "place": {"winner": 1, "prize": rng.choice([2, 3])}.get(result),
                "result": result,
                "team_role": rng.choice(["captain", "member", "member"]),
                "team_name": rng.choice(["Байтовый поток", "Нулевой указатель", "Ctrl+Alt+Win", "Сибирский код", "Красная команда", "Рекурсия"]),
                "event_date": when.isoformat(),
                "verified": True,
            }
        )
    rank = rng.choices(["kms", "1", "2", "3", None], weights=[max(0.05, skill), 1 + skill, 2, 2, max(0.5, 3 - 2 * skill)])[0]
    return {"fsp_id": fsp_id, "name": name, "region": city, "email": email, "sport_rank": rank, "achievements": items}


def link_fsp(db, user: User, participant: dict) -> None:
    db.add(FspLink(user_id=user.id, fsp_id=participant["fsp_id"], display_name=participant["name"], region=participant["region"],
                   sport_rank=participant.get("sport_rank"), last_sync_at=utcnow()))
    for a in participant["achievements"]:
        db.add(
            FspAchievement(
                user_id=user.id, external_id=a["id"], event_name=a["event_name"], discipline=a["discipline"], event_level=a["event_level"],
                place=a["place"], result=a["result"], team_role=a["team_role"], team_name=a["team_name"],
                event_date=date.fromisoformat(a["event_date"]), verified=True, raw=a,
            )
        )
    set_consent(db, user.id, "fsp_data", True)


def seed(per_spec: int, seed_value: int, showcase: bool = True) -> dict:
    rng = random.Random(seed_value)
    # даты рождения — отдельным генератором, чтобы не сдвигать остальные данные набора
    birth_rng = random.Random(seed_value + 1)
    # Воспроизводимость: на платформе сид попытки криптослучайный, а в демо-
    # данных берётся из генератора набора — один --seed даёт одни и те же данные.
    assessment.secrets = SimpleNamespace(randbits=rng.getrandbits)
    db = SessionLocal()
    b = bank()
    truth = {"candidates": {}, "seed": seed_value}
    participants = []
    accounts = {"password": DEMO_PASSWORD, "candidates": [], "employers": []}
    fsp_counter = 200000

    # ---------------------------------------------------------- работодатели
    companies = []
    for i, data in enumerate(COMPANIES):
        owner = make_user(db, "hr%d@demo-fsp.ru" % (i + 1), "employer")
        status = VERIFICATION[i % len(VERIFICATION)]
        company = Company(owner_user_id=owner.id, contact_email=owner.email, inn=demo_inn(i + 1), **data,
                          verification_status=status, verified=status == "verified",
                          verification_requested_at=utcnow() - timedelta(days=3) if status != "none" else None,
                          verified_at=utcnow() - timedelta(days=1) if status == "verified" else None)
        db.add(company)
        db.flush()
        companies.append(company)
        accounts["employers"].append({"email": owner.email, "company": company.name})
    for i, v in enumerate(DEMO_VACANCIES):
        company = companies[i % len(companies)]
        need = Need(company_id=company.id, title=v["title"], specialization=v["specialization"], level=v["level"],
                    description=v["description"], team_description=v["team_description"], stack=v["stack"],
                    work_format=v["work_format"], city=v["city"], salary_from=v["salary_from"], salary_to=v["salary_to"],
                    is_published=True, published_at=utcnow() - timedelta(days=rng.randint(1, 20)))
        need.profile = build_need_profile(need.specialization, need.level, need.stack, need.description, need.team_description)
        db.add(need)
    tasks = [
        ("backend", "Повтор платежа при таймауте", "Шлюз оплаты не ответил за 10 секунд. Как безопасно повторить операцию, не списав деньги дважды?", "approach", None),
        ("backend", "Сколько запросов", "Код загружает 20 заказов, а для каждого — клиента отдельным запросом. Сколько запросов к базе будет выполнено?", "numeric", 21),
        ("frontend", "Гонка запросов в поиске", "Пользователь быстро печатает в поиске, и старые ответы перезаписывают новые. Как это исправить?", "approach", None),
        ("qa", "Граничные значения", "Поле принимает целые числа от 10 до 50 включительно. Сколько значений нужно проверить двухточечным анализом границ?", "numeric", 4),
    ]
    for spec, title, body, kind, number in tasks:
        db.add(EmployerTask(company_id=companies[0].id, specialization=spec, title=title, body=body, kind=kind,
                            answer={"correct_number": float(number), "tolerance": 0.0} if kind == "numeric" else None))
    db.commit()

    # ---------------------------------------------------------- кандидаты
    for spec in ("backend", "frontend", "qa"):
        comps = b.competencies[spec]
        for n in range(per_spec):
            true_level = rng.choices(LEVELS, weights=[4, 4, 2])[0]
            strength = rng.choices(list(STRENGTH), weights=[3, 5, 2])[0]
            profile_name = PROFILE_BY[(true_level, strength)]
            offsets = {c: round(rng.gauss(STRENGTH[strength] * 0.5, 0.12), 3) for c in comps}
            idx = LEVELS.index(true_level)
            declared = LEVELS[max(0, min(2, idx + rng.choices([-1, 0, 1], weights=[15, 60, 25])[0]))]
            email = "%s.%d@demo-fsp.ru" % (spec, n + 1)
            user = make_user(db, email, "candidate")
            name = person(rng)
            city = rng.choice(CITIES)
            typical = ROLE_PROFILES[(spec, true_level)]["typical_stack"]
            true_stack = sorted(set(rng.sample(typical, k=min(len(typical), rng.randint(3, len(typical))))
                                    + rng.sample(EXTRA_STACK[spec], k=rng.randint(2, 6))))
            # заявленный стек: истинный с пропусками и «приукрашиванием»
            declared_stack = [s for s in true_stack if rng.random() < 0.85] + rng.sample(EXTRA_STACK[spec], k=rng.randint(0, 3))
            declared_stack = [s for s in dict.fromkeys(declared_stack) if s in SKILLS]
            lo, hi = SALARY[true_level]
            profile = CandidateProfile(
                user_id=user.id, full_name=name, city=city, contact_email=email,
                phone="+7900%07d" % rng.randint(0, 9_999_999), telegram="@%s_%d" % (spec, n + 1),
                about="Разработчик направления %s. Интересуют продуктовые задачи и сильная команда." % spec,
                experience_years=round(rng.uniform(*EXPERIENCE[true_level]), 1),
                stack=declared_stack, work_formats=rng.sample(["office", "hybrid", "remote"], k=rng.randint(1, 3)),
                relocation=rng.random() < 0.3, salary_expectation=int(rng.uniform(lo, hi) // 5000 * 5000),
                roles=["developer"] if spec != "qa" else [rng.choice(["qa_manual", "qa_automation"])],
                open_to_offers=rng.random() < 0.92,
                privacy={"show_full_name": rng.random() < 0.3, "show_city": True, "show_about": True, "show_fsp": True, "show_experience": True},
                # дата рождения обязательна в опросе; демо-кандидаты — взрослые 20–45 лет
                birth_date=date(2026, 9, 1) - timedelta(days=int(birth_rng.uniform(20, 45) * 365.25)),
            )
            db.add(profile)
            if rng.random() < 0.92:
                set_consent(db, user.id, "profile_publication", True)
            track = pick_track(rng, spec, declared_stack, profile.roles)
            db.add(Survey(user_id=user.id, industry=rng.choice(["fintech", "ecommerce", "gov", "edtech", "telecom", None]),
                          specialization=spec, track=track, self_level=declared,
                          experience_years=profile.experience_years, stack=declared_stack, roles=profile.roles,
                          work_formats=profile.work_formats))
            profile.primary_specialization = spec
            profile.primary_track = track
            db.commit()

            days = rng.uniform(5, 200)
            attempt = take_test(db, rng, user, spec, declared, profile_name, offsets, days)
            applied = attempt.applied or {}
            if applied.get("action") == "recommendation":
                if rng.random() < 0.6:
                    assessment.accept_recommendation(db, user, spec)
                else:
                    assessment.decline_recommendation(db, user, spec)
                    lower = LEVELS[LEVELS.index(declared) - 1]
                    take_test(db, rng, user, spec, lower, profile_name, offsets, days - 0.1)
            elif applied.get("action") == "not_confirmed" and declared != "junior":
                lower = LEVELS[LEVELS.index(declared) - 1]
                take_test(db, rng, user, spec, lower, profile_name, offsets, days - 0.1)
            elif applied.get("promotion_offer") and rng.random() < 0.7:
                # результат выше заявленного: большинство сразу идёт на тест следующего уровня
                take_test(db, rng, user, spec, applied["promotion_offer"]["level"], profile_name, offsets, days - 0.2)
            competencies.recompute(db, user.id, spec)

            if rng.random() < 0.3 + 0.1 * LEVELS.index(true_level):
                fsp_counter += 1
                participant = fsp_participant(rng, "FSP-%06d" % fsp_counter, name, spec, true_level, strength, city, email)
                participants.append(participant)
                link_fsp(db, user, participant)
            # профиль не прошёл тест — тоже бывает, остаётся без категории
            grade = assessment.get_grade(db, user.id, spec)
            if grade is not None and rng.random() < 0.35:
                task = db.scalar(select(EmployerTask).where(EmployerTask.specialization == spec))
                if task is not None:
                    quality = rng.random() < (0.5 + 0.15 * LEVELS.index(true_level))
                    db.add(TaskAssignment(task_id=task.id, candidate_user_id=user.id, status="reviewed",
                                          assigned_at=utcnow() - timedelta(days=rng.randint(3, 40)), due_at=utcnow(),
                                          submitted_at=utcnow() - timedelta(days=rng.randint(1, 30)),
                                          auto_correct=quality if task.kind != "approach" else None,
                                          employer_score=(rng.randint(3, 5) if quality else rng.randint(1, 3)) if task.kind == "approach" else None,
                                          answer={"text": "Решение кандидата"}))
            db.commit()
            truth["candidates"][user.public_id] = {
                "specialization": spec, "true_level": true_level, "strength": strength, "declared_level": declared,
                "competency_offsets": offsets, "true_stack": true_stack, "declared_stack": declared_stack,
                "profile_model": profile_name, "salary_expectation": profile.salary_expectation,
                "work_formats": profile.work_formats, "city": city, "relocation": profile.relocation,
            }

    # ---------------------------------------------------------- демо-учётки
    mod_password = moderator_password()
    moderator = make_user(db, "moderator@demo-fsp.ru", "admin", password=mod_password)
    accounts["moderator"] = {"email": moderator.email, "password": mod_password,
                             "note": "Модерация: компании после жалоб кандидатов и заявки на метку «Компания проверена»"}
    fresh = make_user(db, "candidate@demo-fsp.ru", "candidate")
    db.add(CandidateProfile(user_id=fresh.id, contact_email=fresh.email))
    set_consent(db, fresh.id, "profile_publication", True)
    accounts["candidates"].append({"email": fresh.email, "note": "Новый кандидат: опрос, тест, привязка ФСП ID"})
    # чистые аккаунты для жюри: пройти опрос и тест самим, без регистрации
    accounts["jury"] = []
    for n in range(1, 6):
        jury = make_user(db, "jury%d@demo-fsp.ru" % n, "candidate")
        db.add(CandidateProfile(user_id=jury.id, contact_email=jury.email, full_name="Эксперт %d" % n))
        set_consent(db, jury.id, "profile_publication", True)
        accounts["jury"].append({"email": jury.email, "note": "Чистый кандидат для проверки теста. В тесте есть экспресс-режим (дозаполнить ответы и завершить), повтор без ожидания — кнопка «Сбросить попытки и грейд» в разделе «Категория и тест»"})
    # участники ФСП без привязки — для живой демонстрации привязки
    for i, (name, region) in enumerate([("Алексей Смирнов", "Москва"), ("Мария Кузнецова", "Татарстан"), ("Ольга Белова", "Санкт-Петербург")]):
        participants.insert(i, fsp_participant(rng, "FSP-1000%02d" % (i + 1), name, "backend", "middle", "solid", region,
                                                   "fsp-1000%02d@demo-fsp.ru" % (i + 1)))
    db.commit()
    if showcase:
        showcase_copied_attempt(db, rng, accounts)
        showcase_minor(db, rng, accounts, companies[1])
    for spec in ("backend", "frontend", "qa"):
        accounts["candidates"].append({"email": "%s.1@demo-fsp.ru" % spec, "note": "Кандидат с пройденным тестом (%s)" % spec})

    settings = get_settings()
    (settings.data_dir / "mock_fsp.json").write_text(json.dumps(participants, ensure_ascii=False, indent=1), encoding="utf-8")
    (settings.data_dir / "seed_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    (settings.data_dir / "demo_accounts.json").write_text(json.dumps(accounts, ensure_ascii=False, indent=1), encoding="utf-8")
    graded = db.scalar(select(func.count()).select_from(CandidateGrade))
    attempts = db.scalar(select(func.count()).select_from(Attempt))
    db.close()
    return {"candidates": per_spec * 3, "graded": graded, "attempts": attempts, "fsp_participants": len(participants)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Демонстрационные данные платформы")
    parser.add_argument("--reset", action="store_true", help="удалить все данные перед заполнением")
    parser.add_argument("--per-spec", type=int, default=80, help="кандидатов на специализацию")
    parser.add_argument("--seed", type=int, default=2026, help="сид генератора (воспроизводимость)")
    parser.add_argument("--no-showcase", action="store_true",
                        help="без демонстрационных примеров (пара со списанной попыткой); так запускает валидация")
    parser.add_argument("--if-empty", action="store_true",
                        help="заполнить, только если в базе нет пользователей (запуск контейнера); иначе ничего не делать")
    args = parser.parse_args()
    import app.models  # noqa: F401

    if args.reset:
        Base.metadata.drop_all(engine)
        if engine.dialect.name == "sqlite":
            # SQLite не возвращает освободившееся место сам: без VACUUM файл растёт
            # с каждым пересозданием (после десятка прогонов — сотни мегабайт)
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("VACUUM")
    create_schema()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None and not args.reset:
            if args.if_empty:
                print("В базе уже есть данные — демо-данные не добавляются")
                return
            raise SystemExit("В базе уже есть данные; используйте --reset")
    result = seed(args.per_spec, args.seed, showcase=not args.no_showcase)
    print(json.dumps(result, ensure_ascii=False))
    print("Демо-учётные записи: data/demo_accounts.json; общий пароль %s, пароль модератора — в том же файле" % DEMO_PASSWORD)


if __name__ == "__main__":
    main()
