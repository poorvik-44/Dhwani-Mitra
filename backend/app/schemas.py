from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

CATEGORIES = {"ALARM", "VEHICLE_HORN", "DOORBELL", "KNOCKING", "SIREN"}


class Pulse(BaseModel):
    on_ms: int = Field(ge=20, le=5000)
    off_ms: int = Field(ge=0, le=5000)


class PatternUpdate(BaseModel):
    type: Literal["update_pattern"] = "update_pattern"
    category: str
    intensity: int = Field(ge=0, le=100)
    repeat: int = Field(ge=1, le=8)
    pulses: list[Pulse] = Field(min_length=1, max_length=8)
    preset: str = Field(default="Custom Pattern", max_length=50)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in CATEGORIES:
            raise ValueError("Unknown sound category")
        return normalized


class Detection(BaseModel):
    type: Literal["sound_detected"] = "sound_detected"
    category: str
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in CATEGORIES:
            raise ValueError("Unknown sound category")
        return normalized


def new_event_id() -> str:
    return str(uuid4())
