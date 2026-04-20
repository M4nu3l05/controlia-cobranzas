from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=1)
    confirm_password: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1)
    confirm_password: str = Field(min_length=1)


class UserMeResponse(BaseModel):
    id: int
    email: EmailStr
    username: str
    role: str
    role_label: str
    is_active: bool
    must_change_password: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool
    session_history_id: int | None = None
    user: UserMeResponse


class HealthResponse(BaseModel):
    status: str
    app: str


class MessageResponse(BaseModel):
    message: str


class PasswordResetRequestResponse(BaseModel):
    message: str
    token: str = ""


class LegalAcceptanceStatusResponse(BaseModel):
    has_valid_acceptance: bool
    accepted_terms: bool = False
    accepted_privacy: bool = False
    terms_version: str = ""
    privacy_version: str = ""
    accepted_at: str = ""
    acceptance_source: str = "desktop_app"


class LegalAcceptanceRequest(BaseModel):
    accepted_terms: bool = True
    accepted_privacy: bool = True
    terms_version: str = Field(min_length=1)
    privacy_version: str = Field(min_length=1)
    acceptance_source: str = Field(default="desktop_app", min_length=1)
    client_version: str = ""

