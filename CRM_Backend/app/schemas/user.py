from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class UserListItem(BaseModel):
    id: int
    email: EmailStr
    username: str
    role: str
    role_label: str
    is_active: bool
    must_change_password: bool


class UserCreateRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=60)
    role: str
    temp_password: str = Field(min_length=1)
    confirm_password: str = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=60)
    role: str | None = None
    is_active: bool | None = None


class UserCarteraAssignmentItem(BaseModel):
    empresa: str
    user_id: int | None = None
    email: str = ""
    username: str = ""
    updated_at: str = ""
    updated_by: str = ""


class UserCarteraAssignmentUpdateItem(BaseModel):
    empresa: str
    user_id: int | None = None


class UserCarteraAssignmentBulkRequest(BaseModel):
    assignments: list[UserCarteraAssignmentUpdateItem] = Field(default_factory=list)


class UserCarteraEmpresasResponse(BaseModel):
    user_id: int
    empresas: list[str] = Field(default_factory=list)



class AssistedPasswordResetResponse(BaseModel):
    user: UserListItem
    temporary_password: str
    must_change_password: bool = True
