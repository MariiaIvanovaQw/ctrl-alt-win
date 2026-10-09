"""
Обслуживание данных: удаление того, что больше не нужно хранить.

* копии писем старше outbox_retention_days дней (152-ФЗ: срок хранения);
* незавершённые входы и привязки через ФСП ID с истёкшим сроком;
* использованные и просроченные одноразовые токены почты.

Выполняется при старте и затем раз в час в фоновом потоке.
"""

import logging
import threading

from sqlalchemy import delete, or_

from app.db import SessionLocal, utcnow
from app.models import EmailToken, OidcState
from app.services.mailer import purge_old

log = logging.getLogger("app.maintenance")

INTERVAL_SECONDS = 3600


def run_once() -> dict:
    with SessionLocal() as db:
        mails = purge_old(db)
        states = db.execute(delete(OidcState).where(OidcState.expires_at < utcnow())).rowcount or 0
        tokens = db.execute(
            delete(EmailToken).where(or_(EmailToken.used_at.is_not(None), EmailToken.expires_at < utcnow()))
        ).rowcount or 0
        db.commit()
    if mails or states or tokens:
        log.info("обслуживание: писем %d, сеансов ФСП ID %d, токенов %d удалено", mails, states, tokens)
    return {"emails": mails, "oidc_states": states, "email_tokens": tokens}


class Housekeeper:
    def __init__(self, interval: int = INTERVAL_SECONDS):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="housekeeper", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                run_once()
            except Exception:
                log.exception("ошибка обслуживания данных")
