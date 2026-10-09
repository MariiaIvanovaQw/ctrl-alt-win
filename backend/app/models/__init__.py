"""Все модели регистрируются здесь, чтобы create_schema видел полную схему."""

from app.models.assessment import Attempt, AttemptAnswer
from app.models.candidates import (
    CandidateGrade,
    CandidateProfile,
    CompetencyEstimate,
    GradeHistory,
    GradeRecommendation,
    GuardianConsent,
    Survey,
)
from app.models.employers import Company, Complaint, Need, Selection
from app.models.fsp import FspAchievement, FspLink, OidcState
from app.models.identity import AuditLog, Consent, EmailToken, OutboxEmail, RefreshToken, User
from app.models.integrations import WebhookDelivery, WebhookEndpoint
from app.models.interactions import Application, InteractionEvent, Invitation, Message
from app.models.tasks import EmployerTask, TaskAssignment

__all__ = [
    "Application",
    "Attempt",
    "AttemptAnswer",
    "AuditLog",
    "CandidateGrade",
    "CandidateProfile",
    "Company",
    "CompetencyEstimate",
    "Complaint",
    "Consent",
    "EmailToken",
    "EmployerTask",
    "FspAchievement",
    "FspLink",
    "GradeHistory",
    "GradeRecommendation",
    "GuardianConsent",
    "InteractionEvent",
    "Invitation",
    "Message",
    "Need",
    "OidcState",
    "OutboxEmail",
    "RefreshToken",
    "Selection",
    "Survey",
    "TaskAssignment",
    "User",
    "WebhookDelivery",
    "WebhookEndpoint",
]
