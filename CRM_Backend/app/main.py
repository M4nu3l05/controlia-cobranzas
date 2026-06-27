from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.deudores import router as deudores_router
from app.api.deudores_import import router as deudores_import_router
from app.api.gestiones import router as gestiones_router
from app.api.dashboard import router as dashboard_router
from app.api.templates import router as templates_router
from app.api.operations import router as operations_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.migrations import apply_backend_migrations
from app.models.email_template import EmailTemplate  # noqa: F401
from app.models.session_history import UserSessionHistory  # noqa: F401
from app.models.legal_acceptance import LegalAcceptanceCurrent, LegalAcceptanceEvent  # noqa: F401
from app.models.password_recovery_request import PasswordRecoveryRequest  # noqa: F401
from app.models.reset_token import PasswordResetToken  # noqa: F401
from app.models.operations import (  # noqa: F401
    CarteraTemporaryReplacement,
    CustomerChangeAudit,
    DebtorBirladoTransition,
    DebtorImportBatch,
    DerivationTracking,
    UserNotification,
)
from app.models.payment import (  # noqa: F401
    PaymentAllocation,
    PaymentReceipt,
    PaymentReversal,
    PaymentTransaction,
)
from app.schemas.auth import HealthResponse
from app.services.auth_service import ensure_first_admin
from app.services.template_service import ensure_default_email_templates

settings = get_settings()


def initialize_backend() -> None:
    db = SessionLocal()
    try:
        apply_backend_migrations(db)
        ensure_first_admin(
            db,
            email=settings.first_admin_email,
            username=settings.first_admin_username,
            password=settings.first_admin_password,
        )
        ensure_default_email_templates(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_backend()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="2.0.0",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/", response_model=HealthResponse)
def root():
    return HealthResponse(
        status="ok",
        app=settings.app_name,
    )


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        app=settings.app_name,
    )


@app.get("/health/ready", response_model=HealthResponse)
def readiness():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return HealthResponse(status="ready", app=settings.app_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos no está disponible.",
        ) from exc
    finally:
        db.close()


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(deudores_router)
app.include_router(deudores_import_router)
app.include_router(gestiones_router)


app.include_router(dashboard_router)
app.include_router(templates_router)
app.include_router(operations_router)



