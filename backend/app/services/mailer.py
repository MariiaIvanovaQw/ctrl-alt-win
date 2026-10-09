"""
Отправка писем.

Копия каждого письма сохраняется в таблицу outbox_emails базы платформы
(это не почтовый ящик получателя). Если задан SMTP (в docker-compose это
Mailpit), письмо отправляется сразу. Копии хранятся outbox_retention_days
дней и удаляются вместе с учётной записью адресата.

kind — назначение письма. В демо-режиме служебный /dev/mailbox отдаёт
только письма подтверждения адреса (kind=verify_email): остальные письма
(ссылки законному представителю, восстановление пароля, уведомления)
через него не видны.
"""

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import OutboxEmail

log = logging.getLogger("app.mail")

SUBJECT_MAX = 255  # длина колонки outbox_emails.subject


def send_email(db: Session, to_email: str, subject: str, body: str, kind: str = "notice") -> OutboxEmail:
    settings = get_settings()
    if len(subject) > SUBJECT_MAX:
        # название компании и должности приходят от пользователя: тема может не влезть в колонку
        subject = subject[: SUBJECT_MAX - 1] + "…"
    record = OutboxEmail(to_email=to_email, subject=subject, body=body, kind=kind)
    db.add(record)
    if settings.smtp_host:
        message = EmailMessage()
        message["From"] = settings.mail_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            record.sent_at = utcnow()
        except (OSError, smtplib.SMTPException) as exc:
            record.error = str(exc)[:500]
            log.warning("письмо %s не отправлено: %s", to_email, exc)
    else:
        log.info("письмо для %s: %s", to_email, subject)
    return record


def forget_recipient(db: Session, *addresses: str | None) -> int:
    """Удаляет копии писем на эти адреса (удаление учётной записи, 152-ФЗ)."""
    emails = {a.strip().lower() for a in addresses if a}
    if not emails:
        return 0
    return db.execute(
        delete(OutboxEmail).where(func.lower(OutboxEmail.to_email).in_(emails)).execution_options(synchronize_session=False)
    ).rowcount or 0


def purge_old(db: Session) -> int:
    """Удаляет копии писем старше outbox_retention_days дней."""
    days = get_settings().outbox_retention_days
    if days <= 0:
        return 0
    removed = db.execute(delete(OutboxEmail).where(OutboxEmail.created_at < utcnow() - timedelta(days=days))).rowcount
    db.commit()
    return removed or 0
