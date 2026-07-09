"""Pydantic request/response models."""
from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    # FIX #28: enforce non-empty, bounded fields.
    org_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class RoomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # FIX #29: capacity and rate must be positive values.
    capacity: int = Field(ge=1)
    hourly_rate_cents: int = Field(ge=1)


class BookingCreateRequest(BaseModel):
    room_id: int
    start_time: str
    end_time: str
