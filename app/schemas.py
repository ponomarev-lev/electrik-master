from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .validation import (
    normalize_phone,
    parse_birth_date,
    validate_first_name,
    validate_last_name,
    validate_middle_name,
    validate_sex,
)


class EmployeePayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    last_name: str
    first_name: str
    middle_name: str | None = None
    phone: str
    birth_date: date
    sex: Literal["male", "female"]
    photo_path: str | None = None

    @field_validator("last_name")
    @classmethod
    def _validate_last_name(cls, value: str) -> str:
        return validate_last_name(value)

    @field_validator("first_name")
    @classmethod
    def _validate_first_name(cls, value: str) -> str:
        return validate_first_name(value)

    @field_validator("middle_name")
    @classmethod
    def _validate_middle_name(cls, value: str | None) -> str | None:
        return validate_middle_name(value)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("birth_date", mode="before")
    @classmethod
    def _validate_birth_date(cls, value: str | date) -> date:
        return parse_birth_date(value)

    @field_validator("sex")
    @classmethod
    def _validate_sex(cls, value: str) -> str:
        return validate_sex(value)
