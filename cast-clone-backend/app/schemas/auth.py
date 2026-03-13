"""Pydantic schemas for authentication and user management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime | None
    last_login: datetime | None

    model_config = {"from_attributes": True}


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8)


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    auth_disabled: bool = False


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8)
    role: Literal["admin", "member"] = "member"


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8)
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None
