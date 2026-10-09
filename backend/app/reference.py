"""
Справочники платформы.

Таксономия навыков связывает слова из резюме и описаний вакансий с
компетенциями банка заданий: так навыки, заявленные текстом, переводятся
в те же единицы, в которых измеряет тест, и подбор сравнивает вакансию
с подтверждёнными результатами, а не с совпадением ключевых слов.
"""

SPECIALIZATIONS = {
    "backend": "Бэкенд-разработка",
    "frontend": "Фронтенд-разработка",
    "qa": "Тестирование (QA)",
}

# Отрасль в смысле ТЗ — IT-направление (уточнение постановщиков на встрече):
# по нему строится категория и собирается тест. Направления без готового
# банка заданий показываются в справочнике как запланированные.
DIRECTIONS_PLANNED = {
    "ml": "Машинное обучение и данные",
    "analytics": "Аналитика",
    "devops": "DevOps и инфраструктура",
    "mobile": "Мобильная разработка",
}

# Специализация внутри IT-направления. На тест и грейд не влияет (тест один
# на направление и уровень), уточняет профиль и поиск работодателя.
TRACKS = {
    "backend": {
        "python": "Python",
        "java": "Java / Kotlin",
        "go": "Go",
        "nodejs": "Node.js",
        "php": "PHP",
        "dotnet": "C# / .NET",
        "cpp": "C++",
    },
    "frontend": {
        "react": "React",
        "vue": "Vue",
        "angular": "Angular",
        "vanilla": "JavaScript / TypeScript без фреймворка",
    },
    "qa": {
        "manual": "Ручное тестирование",
        "automation": "Автоматизация тестирования",
        "mobile": "Тестирование мобильных приложений",
        "performance": "Нагрузочное тестирование",
    },
}


def track_title(specialization: str | None, track: str | None) -> str | None:
    if not specialization or not track:
        return None
    return TRACKS.get(specialization, {}).get(track)


# Все суммы на платформе — до вычета НДФЛ (гросс): вилки в вакансиях и
# приглашениях и ожидания кандидатов сравниваются на одной основе.
SALARY_BASIS = "gross"
SALARY_NOTE = "до вычета НДФЛ"

LEVELS = ("junior", "middle", "senior")
LEVEL_TITLES = {
    "junior": "Junior — решает типовые задачи под руководством",
    "middle": "Middle — самостоятельно ведёт задачи и диагностирует проблемы",
    "senior": "Senior — отвечает за решения уровня системы и рисков",
}
LEVEL_INDEX = {"below_junior": 0, "junior": 1, "middle": 2, "senior": 3}

# Предметная область (бизнес-отрасль) — необязательное уточнение интересов
# кандидата и направление деятельности компании. Не путать с «отраслью» ТЗ.
INDUSTRIES = {
    "fintech": "Финтех и банки",
    "ecommerce": "Электронная коммерция",
    "gov": "Госсектор",
    "edtech": "Образование",
    "healthtech": "Медицина",
    "telecom": "Телеком",
    "gamedev": "Игры",
    "industry": "Промышленность",
    "media": "Медиа и развлечения",
    "logistics": "Логистика и транспорт",
    "other": "Другое",
}

WORK_FORMATS = {"office": "Офис", "hybrid": "Гибрид", "remote": "Удалённо"}

TEAM_ROLES = {
    "developer": "Разработчик",
    "team_lead": "Тимлид",
    "tech_lead": "Техлид",
    "architect": "Архитектор",
    "qa_manual": "Тестировщик (ручное)",
    "qa_automation": "Инженер автоматизации тестирования",
    "mentor": "Наставник",
}

SOFT_SKILLS = {
    "communication": ("Коммуникация", ("коммуникаб", "коммуникац", "общител")),
    "teamwork": ("Работа в команде", ("командн", "в команде", "team player")),
    "responsibility": ("Ответственность", ("ответствен",)),
    "learning": ("Обучаемость", ("обучаем", "быстро учусь", "самообуч")),
    "mentoring": ("Наставничество", ("наставни", "менторств", "mentor")),
    "leadership": ("Лидерство", ("лидерск", "руководил", "лидер")),
    "analytical": ("Аналитическое мышление", ("аналитическ", "системное мышление")),
    "stress": ("Стрессоустойчивость", ("стрессоустойчив",)),
}

COMPETENCY_TITLES = {
    "programming_language": "Язык программирования",
    "algorithms": "Алгоритмы",
    "data_structures": "Структуры данных",
    "databases": "Базы данных",
    "sql": "SQL",
    "http": "HTTP",
    "rest_api": "Проектирование REST API",
    "auth": "Аутентификация и авторизация",
    "security": "Безопасность",
    "performance": "Производительность",
    "caching": "Кэширование",
    "concurrency": "Конкурентность",
    "architecture": "Архитектура",
    "scalability": "Масштабирование",
    "git": "Git",
    "testing": "Тестирование кода",
    "html": "HTML",
    "css": "CSS",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "react": "React",
    "state_management": "Управление состоянием",
    "components": "Компоненты",
    "api_integration": "Работа с API",
    "browser": "Браузер и DOM",
    "accessibility": "Доступность",
    "requirements_analysis": "Анализ требований",
    "test_design": "Тест-дизайн",
    "test_cases": "Тест-кейсы",
    "checklists": "Чек-листы",
    "bug_reports": "Баг-репорты",
    "functional_testing": "Функциональное тестирование",
    "regression_testing": "Регрессионное тестирование",
    "integration_testing": "Интеграционное тестирование",
    "api_testing": "Тестирование API",
    "test_automation": "Автоматизация тестирования",
    "load_testing": "Нагрузочное тестирование",
    "risk_analysis": "Анализ рисков",
    "defect_prioritization": "Приоритизация дефектов",
    "test_documentation": "Тестовая документация",
}

# slug: (название, синонимы для поиска в тексте, {специализация: [компетенции банка]})
# Синоним с «*» на конце ищется как начало слова (для русских словоформ).
SKILLS = {
    # языки
    "python": ("Python", ("python", "питон"), {"backend": ["programming_language"], "qa": ["test_automation"]}),
    "java": ("Java", ("java",), {"backend": ["programming_language"], "qa": ["test_automation"]}),
    "go": ("Go", ("golang", "go-разработ*"), {"backend": ["programming_language", "concurrency"]}),
    "csharp": ("C#", ("c#", ".net", "dotnet", "asp.net"), {"backend": ["programming_language"]}),
    "kotlin": ("Kotlin", ("kotlin",), {"backend": ["programming_language"]}),
    "php": ("PHP", ("php",), {"backend": ["programming_language"]}),
    "nodejs": ("Node.js", ("node.js", "nodejs", "node js"), {"backend": ["programming_language", "concurrency"]}),
    "javascript": ("JavaScript", ("javascript", "js", "ecmascript"), {"frontend": ["javascript"], "qa": ["test_automation"]}),
    "typescript": ("TypeScript", ("typescript", "ts"), {"frontend": ["typescript"], "backend": ["programming_language"]}),
    # бэкенд-фреймворки и протоколы
    "django": ("Django", ("django",), {"backend": ["rest_api", "databases"]}),
    "fastapi": ("FastAPI", ("fastapi",), {"backend": ["rest_api", "http"]}),
    "flask": ("Flask", ("flask",), {"backend": ["rest_api", "http"]}),
    "spring": ("Spring", ("spring", "spring boot"), {"backend": ["rest_api", "architecture"]}),
    "nestjs": ("NestJS", ("nestjs", "nest.js"), {"backend": ["rest_api", "architecture"]}),
    "express": ("Express", ("express",), {"backend": ["rest_api", "http"]}),
    "laravel": ("Laravel", ("laravel",), {"backend": ["rest_api"]}),
    "rest": ("REST API", ("rest", "rest api", "restful"), {"backend": ["rest_api", "http"], "frontend": ["api_integration", "http"], "qa": ["api_testing"]}),
    "grpc": ("gRPC", ("grpc",), {"backend": ["rest_api", "architecture"]}),
    "graphql": ("GraphQL", ("graphql",), {"backend": ["rest_api"], "frontend": ["api_integration"], "qa": ["api_testing"]}),
    "websocket": ("WebSocket", ("websocket", "websockets"), {"backend": ["http"], "frontend": ["api_integration"]}),
    "microservices": ("Микросервисы", ("микросервис*", "microservices"), {"backend": ["architecture", "scalability"], "qa": ["integration_testing"]}),
    "oauth": ("OAuth 2.0 / OIDC", ("oauth", "oauth2", "openid connect", "oidc", "keycloak", "jwt"), {"backend": ["auth", "security"], "frontend": ["security"]}),
    "algorithms": ("Алгоритмы", ("алгоритм*", "algorithms", "структуры данных"), {"backend": ["algorithms", "data_structures"]}),
    # хранение и очереди
    "postgresql": ("PostgreSQL", ("postgresql", "postgres", "постгрес"), {"backend": ["sql", "databases"], "qa": ["sql"]}),
    "mysql": ("MySQL", ("mysql", "mariadb"), {"backend": ["sql", "databases"], "qa": ["sql"]}),
    "sql": ("SQL", ("sql",), {"backend": ["sql"], "qa": ["sql"]}),
    "mongodb": ("MongoDB", ("mongodb", "mongo"), {"backend": ["databases"]}),
    "redis": ("Redis", ("redis",), {"backend": ["caching", "performance"]}),
    "clickhouse": ("ClickHouse", ("clickhouse",), {"backend": ["databases", "performance"]}),
    "elasticsearch": ("Elasticsearch", ("elasticsearch", "elastic", "opensearch"), {"backend": ["databases", "performance"]}),
    "kafka": ("Kafka", ("kafka",), {"backend": ["architecture", "concurrency", "scalability"], "qa": ["integration_testing"]}),
    "rabbitmq": ("RabbitMQ", ("rabbitmq", "rabbit"), {"backend": ["architecture", "concurrency"], "qa": ["integration_testing"]}),
    # инфраструктура
    "docker": ("Docker", ("docker", "докер"), {"backend": ["scalability"], "qa": ["test_automation"]}),
    "kubernetes": ("Kubernetes", ("kubernetes", "k8s"), {"backend": ["scalability", "architecture"]}),
    "linux": ("Linux", ("linux", "bash"), {"backend": ["performance"]}),
    "nginx": ("Nginx", ("nginx",), {"backend": ["http", "performance"]}),
    "ci_cd": ("CI/CD", ("ci/cd", "ci cd", "gitlab ci", "github actions", "jenkins"), {"backend": ["testing"], "frontend": ["testing"], "qa": ["test_automation", "regression_testing"]}),
    "git": ("Git", ("git", "github", "gitlab"), {"backend": ["git"], "frontend": ["git"]}),
    "highload": ("Высокие нагрузки", ("highload", "высоконагруж*", "высокие нагрузки"), {"backend": ["scalability", "performance"]}),
    # фронтенд
    "react": ("React", ("react", "react.js", "reactjs"), {"frontend": ["react", "components"]}),
    "nextjs": ("Next.js", ("next.js", "nextjs"), {"frontend": ["react", "architecture", "performance"]}),
    "vue": ("Vue", ("vue", "vue.js", "nuxt"), {"frontend": ["components", "state_management"]}),
    "angular": ("Angular", ("angular",), {"frontend": ["components", "architecture"]}),
    "redux": ("Redux", ("redux", "rtk"), {"frontend": ["state_management"]}),
    "mobx": ("MobX", ("mobx", "zustand", "effector"), {"frontend": ["state_management"]}),
    "html": ("HTML", ("html", "html5", "вёрстк*", "верстк*"), {"frontend": ["html"]}),
    "css": ("CSS", ("css", "scss", "sass", "less", "tailwind", "css-in-js"), {"frontend": ["css"]}),
    "webpack": ("Сборщики (Webpack, Vite)", ("webpack", "vite", "rollup", "esbuild"), {"frontend": ["performance", "architecture"]}),
    "accessibility": ("Доступность (a11y)", ("a11y", "accessibility", "доступност*", "wcag"), {"frontend": ["accessibility"]}),
    "storybook": ("Storybook", ("storybook", "дизайн-систем*", "design system"), {"frontend": ["components"]}),
    "web_performance": ("Производительность веба", ("web vitals", "core web vitals", "lcp", "inp"), {"frontend": ["performance", "browser"]}),
    "jest": ("Jest / Vitest", ("jest", "vitest", "testing library"), {"frontend": ["testing"], "qa": ["test_automation"]}),
    # тестирование
    "playwright": ("Playwright", ("playwright",), {"frontend": ["testing"], "qa": ["test_automation"]}),
    "cypress": ("Cypress", ("cypress",), {"frontend": ["testing"], "qa": ["test_automation"]}),
    "selenium": ("Selenium", ("selenium", "selenide", "webdriver"), {"qa": ["test_automation"]}),
    "pytest": ("pytest", ("pytest",), {"backend": ["testing"], "qa": ["test_automation"]}),
    "junit": ("JUnit / TestNG", ("junit", "testng"), {"backend": ["testing"], "qa": ["test_automation"]}),
    "allure": ("Allure", ("allure",), {"qa": ["test_automation", "test_documentation"]}),
    "postman": ("Postman", ("postman", "insomnia", "swagger"), {"qa": ["api_testing"]}),
    "load_testing": ("Нагрузочное тестирование", ("jmeter", "k6", "locust", "gatling", "нагрузочн*"), {"qa": ["load_testing"], "backend": ["performance"]}),
    "test_design": ("Тест-дизайн", ("тест-дизайн", "тест дизайн", "test design", "граничн*", "классы эквивалентности", "попарн*"), {"qa": ["test_design"]}),
    "test_cases": ("Тест-кейсы и чек-листы", ("тест-кейс*", "тест кейс*", "test case*", "чек-лист*", "чеклист*"), {"qa": ["test_cases", "checklists"]}),
    "bug_tracking": ("Баг-трекинг (Jira, YouTrack)", ("jira", "youtrack", "баг-репорт*", "bug report*", "дефект*"), {"qa": ["bug_reports", "defect_prioritization"]}),
    "testrail": ("TestRail / Qase / TestIT", ("testrail", "qase", "testit", "zephyr"), {"qa": ["test_documentation", "test_cases"]}),
    "api_testing": ("Тестирование API", ("тестирование api", "api testing", "тестирования api"), {"qa": ["api_testing", "integration_testing"]}),
    "mobile_testing": ("Мобильное тестирование", ("мобильн*", "android", "ios"), {"qa": ["functional_testing"]}),
    "devtools": ("DevTools / Charles", ("devtools", "charles", "fiddler"), {"qa": ["api_testing"], "frontend": ["browser"]}),
}

# Ключевые слова, которые указывают на компетенцию без конкретного инструмента.
COMPETENCY_KEYWORDS = {
    "backend": {
        "security": ("безопасност*", "owasp", "уязвимост*", "pci dss", "152-фз"),
        "performance": ("производительност*", "оптимизац*", "профилирова*", "latency", "задержк*"),
        "caching": ("кэш*", "кеш*", "cache"),
        "concurrency": ("конкурент*", "параллел*", "асинхрон*", "многопоточ*", "идемпотентн*"),
        "architecture": ("архитектур*", "ddd", "saga", "событийн*", "event-driven"),
        "scalability": ("масштабир*", "отказоустойчив*", "шардир*", "реплика*"),
        "databases": ("транзакц*", "индекс*", "миграц*", "баз* данных"),
        "sql": ("запрос*", "sql"),
        "rest_api": ("api", "контракт*", "openapi"),
        "auth": ("авторизац*", "аутентификац*", "sso"),
        "testing": ("тест*", "покрыти*"),
        "algorithms": ("алгоритм*",),
    },
    "frontend": {
        "performance": ("производительност*", "оптимизац*", "web vitals", "бандл*"),
        "accessibility": ("доступност*", "a11y", "скринридер*"),
        "security": ("xss", "csp", "безопасност*"),
        "architecture": ("архитектур*", "микрофронтенд*", "монорепозитор*", "fsd"),
        "state_management": ("состояни*", "стор*", "store"),
        "api_integration": ("api", "интеграц*", "rest"),
        "components": ("компонент*", "ui-kit", "ui kit"),
        "testing": ("тест*",),
        "browser": ("браузер*", "dom", "service worker"),
    },
    "qa": {
        "requirements_analysis": ("требовани*", "критери* приёмки", "критерии приемки", "user stor*"),
        "risk_analysis": ("риск*",),
        "regression_testing": ("регресс*",),
        "integration_testing": ("интеграц*", "микросервис*"),
        "load_testing": ("нагрузк*", "нагрузочн*", "производительност*"),
        "test_automation": ("автоматизац*", "автотест*"),
        "functional_testing": ("функциональн*", "ручн*", "smoke", "дымов*"),
        "test_documentation": ("документац*", "тест-план*", "стратеги*"),
        "sql": ("sql", "баз* данных"),
        "api_testing": ("api",),
    },
}

# ---------------------------------------------------------------- ФСП

FSP_DISCIPLINES = {
    "product": "Продуктовое программирование",
    "algorithmic": "Алгоритмическое программирование",
    "security": "Программирование систем информационной безопасности",
    "robotics": "Программирование робототехники",
    "uav": "Программирование беспилотных авиационных систем",
}

# Спортивные разряды и звания по спортивному программированию (ЕВСК).
FSP_SPORT_RANKS = {
    "ms": "Мастер спорта",
    "kms": "Кандидат в мастера спорта",
    "1": "I спортивный разряд",
    "2": "II спортивный разряд",
    "3": "III спортивный разряд",
    "1y": "I юношеский разряд",
}

# Уровень мероприятия показывается работодателю, но на вес не влияет:
# постановщики просили не ранжировать соревнования между собой.
FSP_EVENT_LEVELS = {
    "international": "Международные",
    "federal": "Всероссийские",
    "regional": "Региональные и межрегиональные",
    "local": "Муниципальные и вузовские",
}

FSP_RESULTS = {
    "winner": "Победитель",
    "prize": "Призёр",
    "finalist": "Финалист",
    "participant": "Участник",
}
