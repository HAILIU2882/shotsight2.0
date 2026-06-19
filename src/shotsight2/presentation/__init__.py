"""Presentation layer: server-rendered HTML pages for ShotSight 2.0.

Registers all presentation routes and provides template infrastructure.
No direct persistence, filesystem, or computer-vision imports are allowed
in this package — all data comes through the Application API DI providers.
"""

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shotsight2.presentation.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, t

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

jinja_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
jinja_templates.env.globals["t"] = t
jinja_templates.env.globals["SUPPORTED_LOCALES"] = SUPPORTED_LOCALES
jinja_templates.env.globals["DEFAULT_LOCALE"] = DEFAULT_LOCALE


def register_presentation(app: FastAPI) -> None:
    """Mount static assets and attach all presentation routers to the app."""
    from shotsight2.presentation.routes import (
        attempts,
        calibration,
        deletion,
        library,
        players,
        statistics,
        tracking_repair,
        upload,
        video_detail,
    )

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(library.router)
    app.include_router(upload.router)
    app.include_router(video_detail.router)
    app.include_router(calibration.router)
    app.include_router(players.router)
    app.include_router(attempts.router)
    app.include_router(statistics.router)
    app.include_router(tracking_repair.router)
    app.include_router(deletion.router)

    @app.get("/preferences/language-ui", tags=["presentation"])
    def switch_locale(locale: str = Query(default=DEFAULT_LOCALE)) -> RedirectResponse:
        """Redirect to the library with the chosen locale as a query param."""
        safe = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        response = RedirectResponse(url=f"/?locale={safe}", status_code=303)
        response.set_cookie("locale", safe, max_age=60 * 60 * 24 * 365)
        return response
