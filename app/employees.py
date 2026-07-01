from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Employee


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
settings = get_settings()


@dataclass(frozen=True)
class EmployeeListItem:
    id: int
    full_name: str
    age: int
    phone: str
    sex_value: str
    sex_label: str
    sex_class: str
    photo_url: str | None
    photo_alt: str


def _parse_age_value(raw: str, label: str) -> tuple[int | None, str | None]:
    cleaned = raw.strip()
    if not cleaned:
        return None, None

    if not cleaned.isdigit():
        return None, f"Поле возраста '{label}' должно содержать только цифры."

    value = int(cleaned)
    if value < 0:
        return None, f"Поле возраста '{label}' не может быть меньше 0."

    return value, None


def _build_page_url(
    *,
    search: str,
    male: bool,
    female: bool,
    age_from_raw: str,
    age_to_raw: str,
    page: int,
) -> str:
    params: list[tuple[str, str]] = []
    if search:
        params.append(("search", search))
    if male:
        params.append(("male", "true"))
    if female:
        params.append(("female", "true"))
    if age_from_raw.strip():
        params.append(("age_from", age_from_raw.strip()))
    if age_to_raw.strip():
        params.append(("age_to", age_to_raw.strip()))
    params.append(("page", str(page)))
    return f"/employees?{urlencode(params)}"


def _to_list_item(employee: Employee, age: int) -> EmployeeListItem:
    sex_label = "Муж." if employee.sex == "male" else "Жен."
    sex_class = "sex-male" if employee.sex == "male" else "sex-female"
    photo_url = f"/media/{employee.photo_path}" if employee.photo_path else None
    return EmployeeListItem(
        id=employee.id,
        full_name=employee.full_name,
        age=age,
        phone=employee.phone,
        sex_value=employee.sex,
        sex_label=sex_label,
        sex_class=sex_class,
        photo_url=photo_url,
        photo_alt=employee.full_name,
    )


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/employees", status_code=302)


@router.get("/employees")
def employees_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query(default="", alias="search"),
    male: bool = Query(default=False),
    female: bool = Query(default=False),
    age_from: str = Query(default=""),
    age_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
) -> object:
    employees = db.execute(select(Employee).order_by(Employee.id.asc())).scalars().all()

    search_value = " ".join(q.split()).strip()
    search_needle = search_value.lower()

    age_errors: list[str] = []
    age_from_value, age_from_error = _parse_age_value(age_from, "с")
    age_to_value, age_to_error = _parse_age_value(age_to, "по")
    if age_from_error:
        age_errors.append(age_from_error)
    if age_to_error:
        age_errors.append(age_to_error)
    if (
        age_from_value is not None
        and age_to_value is not None
        and age_from_value > age_to_value
    ):
        age_errors.append("Значение возраста 'с' не может быть больше значения 'по'.")

    sex_filtered: list[Employee] = []
    for employee in employees:
        if male and not female and employee.sex != "male":
            continue
        if female and not male and employee.sex != "female":
            continue
        sex_filtered.append(employee)

    ranged: list[tuple[Employee, int]] = []
    apply_age_range = not age_errors
    for employee in sex_filtered:
        age = employee.calculate_age()
        if apply_age_range and age_from_value is not None and age < age_from_value:
            continue
        if apply_age_range and age_to_value is not None and age > age_to_value:
            continue
        ranged.append((employee, age))

    searched: list[tuple[Employee, int]] = []
    if search_needle:
        for employee, age in ranged:
            searchable = f"{employee.full_name} {age} {employee.phone}".lower()
            if search_needle in searchable:
                searched.append((employee, age))
    else:
        searched = ranged

    total_items = len(searched)
    total_pages = max(1, ceil(total_items / settings.page_size)) if total_items else 1
    current_page = min(page, total_pages)

    offset = (current_page - 1) * settings.page_size
    paged = searched[offset : offset + settings.page_size]
    items = [_to_list_item(employee, age) for employee, age in paged]

    page_links = [
        {
            "number": page_number,
            "url": _build_page_url(
                search=search_value,
                male=male,
                female=female,
                age_from_raw=age_from,
                age_to_raw=age_to,
                page=page_number,
            ),
            "is_current": page_number == current_page,
        }
        for page_number in range(1, total_pages + 1)
    ]

    return templates.TemplateResponse(
        request=request,
        name="employees/list.html",
        context={
            "search": search_value,
            "male": male,
            "female": female,
            "age_from": age_from,
            "age_to": age_to,
            "age_errors": age_errors,
            "page": current_page,
            "employees": items,
            "total_items": total_items,
            "page_links": page_links,
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


@router.get("/employees/{employee_id}/edit")
def employee_edit_form(
    request: Request,
    employee_id: int,
    db: Session = Depends(get_db),
) -> object:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден.")

    return templates.TemplateResponse(
        request=request,
        name="employees/form.html",
        context={
            "mode": "edit",
            "employee": {
                "id": employee.id,
                "last_name": employee.last_name,
                "first_name": employee.first_name,
                "middle_name": employee.middle_name or "",
                "phone": employee.phone,
                "birth_date": employee.birth_date.isoformat(),
                "sex": employee.sex,
            },
            "errors": {},
        },
    )


@router.post("/employees/{employee_id}/delete")
def employee_delete(
    employee_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    employee = db.get(Employee, employee_id)
    if employee is not None:
        db.delete(employee)
        db.commit()
    return RedirectResponse(url="/employees", status_code=303)
