"""Shared locale dependency for presentation routes."""

from fastapi import Cookie, Query

from shotsight2.presentation.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES


def locale_param(
    locale: str = Query(default=DEFAULT_LOCALE),
    locale_cookie: str | None = Cookie(default=None, alias="locale"),
) -> str:
    """Resolve the active locale from query param (highest priority) or cookie."""
    candidate = locale or locale_cookie or DEFAULT_LOCALE
    return candidate if candidate in SUPPORTED_LOCALES else DEFAULT_LOCALE
