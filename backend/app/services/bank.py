"""
Адаптер к банку заданий it-assessment-bank.

Бэкенд не дублирует алгоритмы банка: сборка теста, подсчёт баллов и
определение грейда вызываются из эталонной реализации tools/ (она без
внешних зависимостей). Задания читаются из собранного dist/bank.json.
Так банк и платформа не расходятся: правка порогов в blueprint.py сразу
действует и в симуляции, и в API.
"""

import importlib
import json
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType

from app.config import get_settings

_import_lock = threading.Lock()


@dataclass
class Bank:
    version: str
    items: list[dict]
    pools: dict[str, list[dict]]
    by_id: dict[str, dict]
    competencies: dict[str, list[str]]
    roles: dict[str, dict]
    lib: ModuleType  # bank_lib
    blueprint: ModuleType
    assembler: ModuleType  # assemble_test
    grading: ModuleType

    def assemble(self, specialization: str, level: str, seed: int) -> dict:
        return self.assembler.assemble_test(self.pools[specialization], specialization, level, seed)

    def score(self, keys: list[dict], submitted_by_item: dict) -> dict:
        return self.assembler.score_attempt(keys, submitted_by_item)

    def grade(self, result: dict, specialization: str, level: str) -> dict:
        return self.grading.determine_grade(result, specialization, level)

    def result_document(self, candidate_id: str, test: dict, submitted_by_item: dict, finished_at: str) -> dict:
        return self.assembler.build_result_document(candidate_id, test, submitted_by_item, finished_at)

    def simulator(self) -> ModuleType:
        return _import_tool("simulate_candidates")


def _import_tool(name: str) -> ModuleType:
    tools = str(get_settings().bank_tools)
    with _import_lock:
        if tools not in sys.path:
            sys.path.insert(0, tools)
        return importlib.import_module(name)


@lru_cache
def bank() -> Bank:
    settings = get_settings()
    with open(settings.bank_json, encoding="utf-8") as fh:
        data = json.load(fh)
    items = data["items"]
    pools = {spec: [i for i in items if i["specialization"] == spec] for spec in data["specializations"]}
    return Bank(
        version=data["bank_version"],
        items=items,
        pools=pools,
        by_id={i["id"]: i for i in items},
        competencies=data["competencies"],
        roles=data["competency_roles"],
        lib=_import_tool("bank_lib"),
        blueprint=_import_tool("blueprint"),
        assembler=_import_tool("assemble_test"),
        grading=_import_tool("grading"),
    )
