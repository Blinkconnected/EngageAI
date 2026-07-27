"""Validation schema for ``Company.settings`` writes (``PATCH /company``).

``Company.settings`` itself stays a schemaless JSON blob at the ORM layer
(see ``infrastructure.database.models.company`` — deliberate, so the set
of admin-console settings can keep growing without a migration), but a
client-supplied *write* to it is exactly the kind of request-shape
validation Pydantic exists for. Every field here is optional: a PATCH
only ever sends the top-level section(s) the caller's UI tab actually
edited, and ``CompanyService.update`` shallow-merges whichever of these
top-level keys were provided into the existing dict, leaving every other
section untouched — see ``docs/architecture/company-onboarding.md``.

Reads that need to check a specific flag (e.g. "is ERP enabled for this
company") go through ``domain.company_settings`` instead of this module —
that module is framework-free and usable from the application layer,
which must not depend on this API-layer schema.
"""

import re
from typing import Literal, get_args
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from blinkengage.domain.notification_types import is_known_notification_type

_HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_VALID_TIMEZONES = available_timezones()

# The Literal type is the single source of truth; SUPPORTED_LANGUAGES is
# derived from it (via get_args) for runtime uses (e.g. rendering the
# frontend's language picker options) — this keeps mypy able to check
# `Literal[*SUPPORTED_LANGUAGES]` below statically, which it can't do
# against a plain `tuple[str, ...]`.
SupportedLanguage = Literal["en", "ar", "fr", "es"]
SUPPORTED_LANGUAGES: tuple[str, ...] = get_args(SupportedLanguage)


class BusinessHoursDay(BaseModel):
    open: str = "09:00"
    close: str = "17:00"
    closed: bool = False

    @field_validator("open", "close")
    @classmethod
    def _check_hhmm(cls, value: str) -> str:
        if not _HHMM_PATTERN.match(value):
            raise ValueError("Time must be in 24-hour HH:MM format")
        return value


class BusinessHoursSettingsUpdate(BaseModel):
    enabled: bool = False
    schedule: dict[str, BusinessHoursDay] | None = None

    @field_validator("schedule")
    @classmethod
    def _check_known_days(
        cls, value: dict[str, BusinessHoursDay] | None
    ) -> dict[str, BusinessHoursDay] | None:
        if value is None:
            return value
        unknown = set(value) - set(_WEEKDAYS)
        if unknown:
            raise ValueError(f"Unknown day(s) in schedule: {sorted(unknown)}")
        return value


class MessagingSettingsUpdate(BaseModel):
    typing_indicator_enabled: bool = True


class SecuritySettingsUpdate(BaseModel):
    min_password_length: int = Field(default=10, ge=10, le=72)


class AiSettingsUpdate(BaseModel):
    enabled: bool = True


class ErpSettingsUpdate(BaseModel):
    enabled: bool = False


class OnboardingSettingsUpdate(BaseModel):
    completed: bool = False


class CompanySettingsUpdate(BaseModel):
    """Every field is a full replacement of that top-level section — a
    settings tab always sends its own section's complete current state,
    not a sparse per-field patch within the section."""

    onboarding: OnboardingSettingsUpdate | None = None
    # No `branding` section here — the logo is managed exclusively via
    # POST/DELETE /company/logo (see api/v1/endpoints/company.py), not a
    # generic settings PATCH, since it's a file upload, not a form field.
    language: SupportedLanguage | None = None
    timezone: str | None = None
    business_hours: BusinessHoursSettingsUpdate | None = None
    notifications: dict[str, bool] | None = None
    messaging: MessagingSettingsUpdate | None = None
    security: SecuritySettingsUpdate | None = None
    ai: AiSettingsUpdate | None = None
    erp: ErpSettingsUpdate | None = None

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_TIMEZONES:
            raise ValueError(f"Unknown IANA timezone: {value!r}")
        return value

    @field_validator("notifications")
    @classmethod
    def _check_notification_types(cls, value: dict[str, bool] | None) -> dict[str, bool] | None:
        if value is None:
            return value
        unknown = [code for code in value if not is_known_notification_type(code)]
        if unknown:
            raise ValueError(f"Unknown notification type(s): {sorted(unknown)}")
        return value
