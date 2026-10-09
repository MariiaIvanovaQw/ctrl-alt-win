"""
Нагрузочная проверка: десятки одновременных пользователей (ТЗ, раздел 3.5).

Против запущенного сервера с демо-данными (scripts/seed_demo.py) N
виртуальных пользователей одновременно выполняют основные операции:

* работодатель – категории, подборка под потребность, поиск по банку,
  карточка кандидата;
* кандидат – статус тестирования, рекомендованные вакансии, приглашения.

Между действиями пользователь «думает» 1-3 секунды (--think), как
настоящий человек. С --think 0 получается стресс-тест: все пользователи
шлют запросы без пауз, и видна предельная пропускная способность процесса.

Для каждой операции считаются медиана, 95-й перцентиль и максимум времени
ответа, а также ошибки. Это оценка на одной машине разработчика и на
SQLite. На сервере с PostgreSQL и несколькими процессами uvicorn запас
больше.

Запуск (сервер уже работает, из каталога backend):
    python -m scripts.benchmark --users 50 --rounds 5                             # реалистичная нагрузка
    python -m scripts.benchmark --users 30 --rounds 5 --think 0 --out stress   # стресс-тест

Несколько процессов: в Linux и Docker – `uvicorn --workers N` за одним адресом.
В Windows общий сокет процессов uvicorn изредка теряет соединения, поэтому
там запускают N отдельных процессов на разных портах и передают их адреса
через запятую (--base-url http://127.0.0.1:8000,http://127.0.0.1:8001,…):
пользователи распределяются по процессам по кругу, как за балансировщиком.
Отчёт: reports/benchmark.md (reports/<--out>.md)
"""

import argparse
import json
import random
import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def login(http: httpx.Client, email: str, password: str) -> dict:
    r = http.post("/api/v1/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Нагрузочная проверка API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="адрес API; несколько – через запятую")
    parser.add_argument("--users", type=int, default=30, help="одновременных пользователей")
    parser.add_argument("--rounds", type=int, default=5, help="повторов сценария каждым пользователем")
    parser.add_argument("--think", type=float, default=2.0, help="средняя пауза между действиями, с (0 – стресс-тест)")
    parser.add_argument("--out", default="benchmark", help="имя отчёта в reports/")
    parser.add_argument("--note", default="один процесс uvicorn, SQLite", help="описание сервера для отчёта")
    args = parser.parse_args()
    bases = [u.strip() for u in args.base_url.split(",") if u.strip()]

    with httpx.Client(base_url=bases[0], timeout=30) as http:
        accounts = http.get("/api/v1/dev/demo-accounts").json()
        password = accounts["password"]
        employers = [login(http, e["email"], password) for e in accounts["employers"]]
        candidates = [login(http, c["email"], password) for c in accounts["candidates"][1:]]
        needs = [http.get("/api/v1/employer/needs", headers=h).json() for h in employers]
        candidate_ids = [r["candidate"]["candidate_id"] for r in
                         http.post("/api/v1/employer/candidates/search", headers=employers[0],
                                   json={"limit": 50}).json()["items"]]

    timings: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    lock = threading.Lock()

    def call(http: httpx.Client, name: str, method: str, url: str, **kwargs) -> None:
        if args.think > 0:
            time.sleep(random.uniform(args.think * 0.5, args.think * 1.5))
        start = time.perf_counter()
        try:
            response = http.request(method, url, **kwargs)
            ok = response.status_code < 400
        except httpx.HTTPError:
            ok = False
        elapsed = (time.perf_counter() - start) * 1000
        with lock:
            timings[name].append(elapsed)
            if not ok:
                errors[name] += 1

    def employer_user(i: int) -> None:
        h = employers[i % len(employers)]
        need = needs[i % len(needs)][0]
        with httpx.Client(base_url=bases[(i // 2) % len(bases)], timeout=30) as http:
            for r in range(args.rounds):
                call(http, "Категории", "GET", "/api/v1/employer/categories", headers=h)
                call(http, "Подборка под потребность", "POST", "/api/v1/employer/needs/%s/selections" % need["id"], headers=h, json={})
                call(http, "Поиск по банку", "POST", "/api/v1/employer/candidates/search", headers=h,
                     json={"specialization": need["specialization"], "has_fsp": r % 2 == 0, "limit": 20})
                call(http, "Карточка кандидата", "GET", "/api/v1/employer/candidates/%s" % candidate_ids[(i + r) % len(candidate_ids)], headers=h)

    def candidate_user(i: int) -> None:
        h = candidates[i % len(candidates)]
        with httpx.Client(base_url=bases[(i // 2) % len(bases)], timeout=30) as http:
            for _ in range(args.rounds):
                call(http, "Статус тестирования", "GET", "/api/v1/candidate/assessment/status", headers=h)
                call(http, "Рекомендованные вакансии", "GET", "/api/v1/candidate/vacancies/recommended", headers=h)
                call(http, "Приглашения", "GET", "/api/v1/candidate/invitations", headers=h)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        futures = [pool.submit(employer_user if i % 2 == 0 else candidate_user, i) for i in range(args.users)]
        for f in futures:
            f.result()
    total = time.perf_counter() - started
    requests = sum(len(v) for v in timings.values())

    rows = []
    for name, values in timings.items():
        values.sort()
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        rows.append({"operation": name, "requests": len(values), "median_ms": statistics.median(values),
                     "p95_ms": p95, "max_ms": values[-1], "errors": errors[name]})
    lines = [
        "# Нагрузочная проверка",
        "",
        "Сформирован `scripts/benchmark.py`: %d одновременных пользователей (половина – работодатели, половина – "
        "кандидаты), по %d повторов сценария, %s; %d запросов за %.1f с (%.1f запросов в секунду), ошибок: %d."
        % (args.users, args.rounds,
           "пауза между действиями %.1f с в среднем" % args.think if args.think > 0 else "без пауз (стресс-тест)",
           requests, total, requests / total, sum(errors.values())),
        "Сервер: %s, демо-данные (240 кандидатов)." % args.note,
        "",
        "| Операция | Запросов | Медиана, мс | 95-й перцентиль, мс | Максимум, мс | Ошибок |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| %s | %d | %.0f | %.0f | %.0f | %d |" % (
            row["operation"], row["requests"], row["median_ms"], row["p95_ms"], row["max_ms"], row["errors"]))
    lines.append("")
    out = ROOT / "reports" / (args.out + ".md")
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    (ROOT / "reports" / (args.out + ".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
