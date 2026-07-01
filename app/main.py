from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from app.config import get_settings
    from app.employees import router as employees_router
else:
    from .config import get_settings
    from .employees import router as employees_router


def create_app() -> FastAPI:
    settings = get_settings()
    app_dir = Path(__file__).resolve().parent
    static_dir = app_dir / "static"
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title=settings.app_name)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")
    app.include_router(employees_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
