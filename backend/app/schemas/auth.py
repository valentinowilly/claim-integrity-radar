"""Strict request and response schemas for local account/session APIs."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.security.auth import validate_password, validate_username

Role = Literal["platform_admin", "data_operator", "verifikator", "audit_lead"]


class LoginRequest(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def username_format(cls, value: str) -> str:
        return validate_username(value)


class UserCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=1024)
    role: Role

    @field_validator("username")
    @classmethod
    def username_format(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        validate_password(value)
        return value


class UserUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    role: Role | None = None
    is_active: bool | None = None


class UserSummary(BaseModel):
    user_id: str
    username: str
    role: Role
    is_active: bool


class SessionResponse(BaseModel):
    user: UserSummary
    permissions: list[str]
    expires_at: str
    csrf_token: str


class UserResponse(BaseModel):
    user: UserSummary


