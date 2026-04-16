from __future__ import annotations

from .constants import TERMS_VERSION, PRIVACY_VERSION
from .dialogs import LegalAcceptanceDialog, LegalDocumentDialog
from .documents import (
    ensure_legal_documents_available,
    get_privacy_text,
    get_terms_text,
)
from .gate import enforce_legal_acceptance

__all__ = [
    "TERMS_VERSION",
    "PRIVACY_VERSION",
    "LegalAcceptanceDialog",
    "LegalDocumentDialog",
    "ensure_legal_documents_available",
    "get_terms_text",
    "get_privacy_text",
    "enforce_legal_acceptance",
]
