"""
Выгрузка спецификации OpenAPI в docs/openapi.json в корне репозитория.
Та же спецификация доступна на работающем сервере: /openapi.json,
/docs (Swagger UI) и /redoc.

Запуск (из каталога backend):
    python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def main() -> None:
    spec = app.openapi()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    operations = sum(len(methods) for methods in spec["paths"].values())
    print("docs/openapi.json: %d путей, %d операций" % (len(spec["paths"]), operations))


if __name__ == "__main__":
    main()
