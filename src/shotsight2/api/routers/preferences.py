"""Language preference update route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from shotsight2.domain.rendering import OverlayLocale

router = APIRouter(prefix="/preferences", tags=["preferences"])

_VALID_LOCALES = {locale.value for locale in OverlayLocale}

# In-process preference store; a persistent adapter can be wired later.
_current_locale: str = OverlayLocale.ENGLISH.value


class LanguagePreferenceRequest(BaseModel):
    """Request body for updating the overlay language preference."""

    locale: str

    @field_validator("locale")
    @classmethod
    def _valid_locale(cls, v: str) -> str:
        if v not in _VALID_LOCALES:
            raise ValueError(f"Unsupported locale: {v!r}. Supported: {sorted(_VALID_LOCALES)}")
        return v


@router.put("/language")
def update_language_preference(body: LanguagePreferenceRequest) -> dict[str, Any]:
    """Set the overlay language preference for artifact rendering.

    Supported locales: en, zh.
    Returns 422 for unknown locale codes.
    """
    global _current_locale
    _current_locale = body.locale
    return {"locale": _current_locale}


@router.get("/language")
def get_language_preference() -> dict[str, Any]:
    """Return the current overlay language preference."""
    return {"locale": _current_locale}
