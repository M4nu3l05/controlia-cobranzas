from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.deudores import router as deudores_router
from app.api.deudores_import import router as deudores_import_router
from app.api.gestiones import router as gestiones_router
from app.api.dashboard import router as dashboard_router
from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.models.legal_acceptance import LegalAcceptanceCurrent, LegalAcceptanceEvent  # noqa: F401
from app.models.password_recovery_request import PasswordRecoveryRequest  # noqa: F401
from app.models.reset_token import PasswordResetToken  # noqa: F401
from app.schemas.auth import HealthResponse
from app.services.auth_service import ensure_first_admin
from app.services.deudor_schema_service import ensure_deudores_optional_columns
from app.services.gestion_service import ensure_gestiones_optional_columns
from app.services.user_service import ensure_cartera_assignments_table

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="0.1.0",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_deudores_optional_columns(db)
        ensure_gestiones_optional_columns(db)
        ensure_first_admin(
            db,
            email=settings.first_admin_email,
            username=settings.first_admin_username,
            password=settings.first_admin_password,
        )
        ensure_cartera_assignments_table(db)
    finally:
        db.close()


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


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(deudores_router)
app.include_router(deudores_import_router)
app.include_router(gestiones_router)


app.include_router(dashboard_router)



