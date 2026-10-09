"""
Переписка внутри платформы по приглашению или отклику.

Кандидат может задать вопросы по приглашению до того, как примет его,
и контакты при этом остаются скрытыми: обмен контактами происходит только
по решению кандидата, как и раньше. Писать можно, пока взаимодействие
активно; закрытая переписка остаётся доступной для чтения.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.errors import Conflict
from app.models import Application, Company, Invitation, Message, User
from app.services import trust
from app.services.interactions import candidate_email
from app.services.mailer import send_email
from app.services.ratelimit import SlidingWindowLimiter

WRITABLE = {
    "invitation": ("sent", "viewed", "accepted"),
    "application": ("sent", "viewed", "invited"),
}
message_limiter = SlidingWindowLimiter(limit=60, window_seconds=3600)


def _other(side: str) -> str:
    return "employer" if side == "candidate" else "candidate"


def unread(db: Session, kind: str, ref_id: uuid.UUID, reader: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.kind == kind, Message.ref_id == ref_id, Message.sender == _other(reader), Message.read_at.is_(None))
    ) or 0


def thread(db: Session, kind: str, obj: Invitation | Application, reader: str) -> list[dict]:
    """Сообщения переписки; входящие отмечаются прочитанными."""
    db.execute(
        update(Message)
        .where(Message.kind == kind, Message.ref_id == obj.id, Message.sender == _other(reader), Message.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    rows = db.scalars(select(Message).where(Message.kind == kind, Message.ref_id == obj.id).order_by(Message.created_at))
    return [
        {"id": str(m.id), "sender": m.sender, "mine": m.sender == reader, "body": m.body,
         "created_at": m.created_at, "read_at": m.read_at}
        for m in rows
    ]


def post(db: Session, kind: str, obj: Invitation | Application, sender: str, user: User, body: str) -> dict:
    if obj.status not in WRITABLE[kind]:
        raise Conflict("Переписка закрыта: взаимодействие завершено", code="thread_closed")
    company = db.get(Company, obj.company_id)
    if sender == "employer":
        trust.ensure_active(company)  # компания на проверке или заблокированная кандидатам не пишет
    message_limiter.hit("msg:%s" % user.id, "Слишком много сообщений, повторите позже")
    message = Message(kind=kind, ref_id=obj.id, sender=sender, sender_user_id=user.id, body=body.strip())
    db.add(message)
    candidate = db.get(User, obj.candidate_user_id)
    if sender == "candidate":
        to = company.contact_email or db.get(User, company.owner_user_id).email
        subject = "Новое сообщение от кандидата %s" % candidate.public_id
    else:
        to = candidate_email(db, candidate)  # контактная почта кандидата, как в остальных уведомлениях
        subject = "Новое сообщение от компании %s" % company.name
    send_email(db, to, subject, "Откройте переписку в личном кабинете, чтобы ответить.")
    db.commit()
    return {"id": str(message.id), "sender": sender, "mine": True, "body": message.body,
            "created_at": message.created_at, "read_at": None}
