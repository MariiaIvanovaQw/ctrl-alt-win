"""
Конфигурация сборки персонального теста и определения грейда.

Это нормативный источник чисел: документация в docs/ ссылается на него,
а не дублирует значения. Все пороги вынесены в константы, чтобы их можно
было менять без правки алгоритма.
"""

# --------------------------------------------------------------------------
# Размер и состав теста
# --------------------------------------------------------------------------

TEST_SIZE = 26

# План сборки: (тип задания, минимальная сложность, максимальная сложность,
# количество заданий). Сумма количеств по каждому уровню равна TEST_SIZE.
#
# Диапазоны сложности подобраны так, чтобы тест одновременно:
#   * надёжно измерял заявленный уровень (основная полоса),
#   * содержал якорные задания уровнем ниже (контроль базы),
#   * содержал задания уровнем выше (возможность подтвердить рост).
BLUEPRINT = {
    "junior": [
        ("theory", 1, 3, 6),
        ("theory", 4, 5, 2),
        ("situational", 1, 3, 7),
        ("situational", 4, 5, 2),
        ("situational", 6, 6, 1),
        ("practical", 1, 3, 5),
        ("practical", 4, 5, 3),
    ],
    "middle": [
        ("theory", 2, 3, 2),
        ("theory", 4, 6, 5),
        ("theory", 7, 8, 1),
        ("situational", 2, 3, 1),
        ("situational", 4, 6, 6),
        ("situational", 7, 8, 3),
        ("practical", 2, 3, 1),
        ("practical", 4, 6, 5),
        ("practical", 7, 8, 2),
    ],
    "senior": [
        ("theory", 4, 6, 2),
        ("theory", 7, 8, 4),
        ("theory", 9, 10, 2),
        ("situational", 4, 6, 2),
        ("situational", 7, 8, 5),
        ("situational", 9, 10, 3),
        ("practical", 4, 6, 1),
        ("practical", 7, 8, 4),
        ("practical", 9, 10, 3),
    ],
}

# Не более такого числа заданий одной компетенции в одной попытке:
# иначе результат по тесту превращается в результат по одной теме.
COMPETENCY_CAP = 4

# Минимальное число различных компетенций в одной попытке.
MIN_COMPETENCIES = 8

# --------------------------------------------------------------------------
# Компетенции
# --------------------------------------------------------------------------

COMPETENCIES = {
    "frontend": [
        "html",
        "css",
        "javascript",
        "typescript",
        "react",
        "state_management",
        "components",
        "api_integration",
        "http",
        "browser",
        "performance",
        "security",
        "accessibility",
        "git",
        "architecture",
        "testing",
    ],
    "backend": [
        "programming_language",
        "algorithms",
        "data_structures",
        "databases",
        "sql",
        "http",
        "rest_api",
        "auth",
        "security",
        "performance",
        "caching",
        "concurrency",
        "architecture",
        "scalability",
        "git",
        "testing",
    ],
    "qa": [
        "requirements_analysis",
        "test_design",
        "test_cases",
        "checklists",
        "bug_reports",
        "functional_testing",
        "regression_testing",
        "integration_testing",
        "api_testing",
        "sql",
        "test_automation",
        "load_testing",
        "risk_analysis",
        "defect_prioritization",
        "test_documentation",
    ],
}

# Компетенции, которые обязаны присутствовать в каждой попытке.
# Для них в банке есть задания всех трёх уровней (проверяется валидатором).
MANDATORY = {
    "frontend": ["javascript", "react", "css", "api_integration", "state_management"],
    "backend": ["sql", "databases", "rest_api", "security", "performance"],
    "qa": ["test_design", "test_cases", "bug_reports", "api_testing", "sql"],
}

# Ключевые компетенции: по ним считается минимальный балл, влияющий на грейд.
KEY = {
    "frontend": [
        "javascript",
        "react",
        "css",
        "api_integration",
        "state_management",
        "components",
        "typescript",
    ],
    "backend": [
        "sql",
        "databases",
        "rest_api",
        "programming_language",
        "algorithms",
        "http",
        "data_structures",
    ],
    "qa": [
        "test_design",
        "test_cases",
        "bug_reports",
        "requirements_analysis",
        "api_testing",
        "functional_testing",
        "checklists",
    ],
}

# Критические компетенции: учитываются только при подтверждении Senior.
CRITICAL = {
    "frontend": ["security", "performance", "architecture"],
    "backend": ["security", "architecture", "scalability", "performance", "concurrency"],
    "qa": ["risk_analysis", "test_automation", "integration_testing", "load_testing"],
}

# --------------------------------------------------------------------------
# Пороги подтверждения грейда
# --------------------------------------------------------------------------

# Минимальное число баллов по компетенции, при котором её результат
# считается достаточно надёжным, чтобы влиять на грейд. В одной попытке
# на компетенцию приходится 1-4 задания, поэтому результат по одной
# компетенции шумный: порог отсекает случаи, где вывод делать нельзя.
COMPETENCY_MIN_POINTS = 4

# Пороги подтверждения грейда заданы отдельно для каждого заявленного
# уровня, потому что у каждого уровня свой план сборки и, значит, своя
# сложность теста. Сравнивать 70 баллов на junior-тесте и 70 баллов на
# senior-тесте нельзя: это разные достижения.
#
# Расшифровка условий:
#   overall_min          — итоговый процент не ниже;
#   easy_rate_min        — доля баллов на заданиях d1-3;
#   mid_rate_min         — доля баллов на заданиях d4-6;
#   mid_plus_rate_min    — доля баллов на заданиях d4-10;
#   mid_plus_solved_min  — число верно решённых заданий d4-10;
#   hard_rate_min        — доля баллов на заданиях d7-10;
#   hard_solved_min      — число верно решённых заданий d7-10;
#   top_rate_min         — доля баллов на заданиях d9-10 (если они были);
#   key_floor            — порог по ключевым компетенциям;
#   key_below_allowed    — сколько ключевых компетенций могут быть ниже порога;
#   critical_avg_min     — средний балл по критическим компетенциям;
#   critical_covered_min — сколько критических компетенций должно быть измерено.
#
# Условия, отсутствующие в наборе, не проверяются.
GRADE_RULES = {
    "junior": {
        "middle": {
            "overall_min": 82,
            "chance_margin_min": 45,
            "mid_plus_rate_min": 0.70,
            "mid_plus_solved_min": 5,
            "key_floor": 45,
            "key_below_allowed": 1,
        },
        "junior": {
            "overall_min": 55,
            "chance_margin_min": 22,
            "easy_rate_min": 0.65,
            "key_floor": 25,
            "key_below_allowed": 3,
        },
    },
    "middle": {
        # Senior по тесту уровня middle не подтверждается: в таком тесте
        # недостаточно заданий d7-10. Для Senior нужно проходить тест Senior.
        "middle": {
            "overall_min": 62,
            "chance_margin_min": 32,
            "mid_plus_rate_min": 0.58,
            "mid_plus_solved_min": 10,
            "key_floor": 40,
            "key_below_allowed": 1,
        },
        "junior": {
            "overall_min": 28,
            "chance_margin_min": 6,
            "easy_rate_min": 0.70,
            "mid_rate_min": 0.33,
            "key_floor": 20,
            "key_below_allowed": 3,
        },
    },
    "senior": {
        "senior": {
            "overall_min": 75,
            "chance_margin_min": 45,
            "hard_rate_min": 0.70,
            "hard_solved_min": 12,
            "top_rate_min": 0.50,
            "key_floor": 50,
            "key_below_allowed": 2,
            "critical_avg_min": 60,
            "critical_covered_min": 2,
        },
        "middle": {
            "overall_min": 30,
            "chance_margin_min": 10,
            "mid_rate_min": 0.60,
            "hard_rate_min": 0.30,
            "key_floor": 30,
            "key_below_allowed": 1,
        },
        "junior": {
            "overall_min": 35,
            "chance_margin_min": 8,
            "mid_rate_min": 0.55,
            "hard_rate_min": 0.20,
            "key_floor": 20,
            "key_below_allowed": 2,
        },
    },
}

# Подтверждённый грейд не может превышать заявленный более чем на один шаг.
MAX_PROMOTION_STEPS = 1

LEVEL_ORDER = ["below_junior", "junior", "middle", "senior"]
