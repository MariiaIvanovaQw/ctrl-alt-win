"""
Тестовые данные заглушки реестра ФСП.

Сид-скрипт пишет полный набор участников в data/mock_fsp.json; если файла
нет, используется небольшой встроенный набор. Все люди и результаты
вымышлены.
"""

import json
from functools import lru_cache

from app.config import get_settings

BUILTIN = [
    {
        "fsp_id": "FSP-100001",
        "name": "Алексей Смирнов",
        "region": "Москва",
        "email": "a.smirnov@demo-fsp.ru",
        "sport_rank": "kms",
        "achievements": [
            {"id": "A-1", "event_name": "Всероссийские соревнования по продуктовому программированию", "discipline": "product",
             "event_level": "federal", "place": 2, "result": "prize", "team_role": "captain", "team_name": "Байтовый поток",
             "event_date": "2025-11-20", "verified": True},
            {"id": "A-2", "event_name": "Кубок России по алгоритмическому программированию", "discipline": "algorithmic",
             "event_level": "federal", "place": None, "result": "finalist", "team_role": "member", "team_name": "Байтовый поток",
             "event_date": "2025-04-12", "verified": True},
        ],
    },
    {
        "fsp_id": "FSP-100002",
        "name": "Мария Кузнецова",
        "region": "Татарстан",
        "email": "m.kuznetsova@demo-fsp.ru",
        "sport_rank": "1",
        "achievements": [
            {"id": "B-1", "event_name": "Чемпионат России по программированию систем информационной безопасности", "discipline": "security",
             "event_level": "federal", "place": 1, "result": "winner", "team_role": "member", "team_name": "Красная команда",
             "event_date": "2026-03-02", "verified": True},
        ],
    },
    {
        "fsp_id": "FSP-100003",
        "name": "Дмитрий Орлов",
        "email": "d.orlov@demo-fsp.ru",
        "sport_rank": None,
        "region": "Новосибирская область",
        "achievements": [
            {"id": "C-1", "event_name": "Региональные соревнования по продуктовому программированию", "discipline": "product",
             "event_level": "regional", "place": None, "result": "participant", "team_role": "member", "team_name": "Сибирский код",
             "event_date": "2024-10-05", "verified": True},
        ],
    },
    {"fsp_id": "FSP-100004", "name": "Ольга Белова", "region": "Санкт-Петербург", "email": "o.belova@demo-fsp.ru",
     "sport_rank": None, "achievements": []},
]


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict[str, dict]:
    path = get_settings().data_dir / "mock_fsp.json"
    participants = BUILTIN
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            participants = json.load(fh)
    return {p["fsp_id"]: p for p in participants}


def participants() -> dict[str, dict]:
    path = get_settings().data_dir / "mock_fsp.json"
    return _load(path.stat().st_mtime if path.exists() else 0.0)
