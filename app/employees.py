from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/employees", status_code=302)


@router.get("/employees")
def employees_list(
    request: Request,
    q: str = Query(default="", alias="search"),
    male: bool = Query(default=False),
    female: bool = Query(default=False),
    age_from: str = Query(default=""),
    age_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
) -> object:
    return templates.TemplateResponse(
        request=request,
        name="employees/list.html",
        context={
            "search": q,
            "male": male,
            "female": female,
            "age_from": age_from,
            "age_to": age_to,
            "page": page,
            "employees": [],
            "today": date.today(),
        },
    )


@router.get("/employees/new")
def employee_create_form(request: Request) -> object:
    return templates.TemplateResponse(
        request=request,
        name="employees/form.html",
        context={
            "mode": "create",
            "employee": {},
            "errors": {},
        },
    )
