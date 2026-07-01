from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Employee
from .schemas import EmployeePayload
from .validation import read_and_validate_photo


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


def _empty_form_employee() -> dict[str, str]:
    return {
        "last_name": "",
        "first_name": "",
        "middle_name": "",
        "phone": "",
        "birth_date": "",
        "sex": "",
    }


def _extract_validation_errors(error: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for item in error.errors():
        field = str(item["loc"][-1])
        if field not in errors:
            errors[field] = item["msg"]
    return errors


def _photo_url(photo_path: str | None) -> str | None:
    return f"/media/{photo_path}" if photo_path else None


def _save_photo_bytes(content: bytes, suffix: str) -> str:
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.{suffix}"
    target = media_dir / filename
    target.write_bytes(content)
    return filename


def _remove_photo_file(photo_path: str | None) -> None:
    if not photo_path:
        return
    target = Path(settings.media_dir) / photo_path
    if target.exists() and target.is_file():
        target.unlink()


def _is_phone_busy(db: Session, phone: str, exclude_employee_id: int | None = None) -> bool:
    stmt = select(Employee).where(Employee.phone == phone)
    if exclude_employee_id is not None:
        stmt = stmt.where(Employee.id != exclude_employee_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _form_employee_payload(
    *,
    last_name: str,
    first_name: str,
    middle_name: str,
    phone: str,
    birth_date: str,
    sex: str,
) -> dict[str, str]:
    return {
        "last_name": last_name,
        "first_name": first_name,
        "middle_name": middle_name,
        "phone": phone,
        "birth_date": birth_date,
        "sex": sex,
    }


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
            "employee": _empty_form_employee(),
            "errors": {},
            "form_action": "/employees/new",
            "current_photo_url": None,
        },
    )


@router.post("/employees/new")
async def employee_create_submit(
    request: Request,
    db: Session = Depends(get_db),
    last_name: str = Form(default=""),
    first_name: str = Form(default=""),
    middle_name: str = Form(default=""),
    phone: str = Form(default=""),
    birth_date: str = Form(default=""),
    sex: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
) -> object:
    employee_data = _form_employee_payload(
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        phone=phone,
        birth_date=birth_date,
        sex=sex,
    )

    errors: dict[str, str] = {}
    payload: EmployeePayload | None = None
    photo_bytes: bytes | None = None
    photo_suffix: str | None = None

    try:
        payload = EmployeePayload(**employee_data)
        employee_data["phone"] = payload.phone
    except ValidationError as error:
        errors.update(_extract_validation_errors(error))

    try:
        photo_bytes, photo_suffix = await read_and_validate_photo(photo)
    except ValueError as error:
        errors["photo"] = str(error)

    if payload is not None and _is_phone_busy(db, payload.phone):
        errors["phone"] = "Сотрудник с таким телефоном уже существует."

    if errors or payload is None:
        return templates.TemplateResponse(
            request=request,
            name="employees/form.html",
            context={
                "mode": "create",
                "employee": employee_data,
                "errors": errors,
                "form_action": "/employees/new",
                "current_photo_url": None,
            },
            status_code=400,
        )

    photo_path: str | None = None
    if photo_bytes is not None and photo_suffix is not None:
        photo_path = _save_photo_bytes(photo_bytes, photo_suffix)

    employee = Employee(
        last_name=payload.last_name,
        first_name=payload.first_name,
        middle_name=payload.middle_name,
        phone=payload.phone,
        birth_date=payload.birth_date,
        sex=payload.sex,
        photo_path=photo_path,
    )
    db.add(employee)
    db.commit()
    return RedirectResponse(url="/employees", status_code=303)


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
            "form_action": f"/employees/{employee.id}/edit",
            "current_photo_url": _photo_url(employee.photo_path),
        },
    )


@router.post("/employees/{employee_id}/edit")
async def employee_edit_submit(
    request: Request,
    employee_id: int,
    db: Session = Depends(get_db),
    last_name: str = Form(default=""),
    first_name: str = Form(default=""),
    middle_name: str = Form(default=""),
    phone: str = Form(default=""),
    birth_date: str = Form(default=""),
    sex: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
) -> object:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден.")

    employee_data = _form_employee_payload(
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        phone=phone,
        birth_date=birth_date,
        sex=sex,
    )
    employee_data["id"] = str(employee_id)

    errors: dict[str, str] = {}
    payload: EmployeePayload | None = None
    photo_bytes: bytes | None = None
    photo_suffix: str | None = None

    try:
        payload = EmployeePayload(**employee_data)
        employee_data["phone"] = payload.phone
    except ValidationError as error:
        errors.update(_extract_validation_errors(error))

    try:
        photo_bytes, photo_suffix = await read_and_validate_photo(photo)
    except ValueError as error:
        errors["photo"] = str(error)

    if payload is not None and _is_phone_busy(db, payload.phone, exclude_employee_id=employee.id):
        errors["phone"] = "Сотрудник с таким телефоном уже существует."

    if errors or payload is None:
        return templates.TemplateResponse(
            request=request,
            name="employees/form.html",
            context={
                "mode": "edit",
                "employee": employee_data,
                "errors": errors,
                "form_action": f"/employees/{employee.id}/edit",
                "current_photo_url": _photo_url(employee.photo_path),
            },
            status_code=400,
        )

    if photo_bytes is not None and photo_suffix is not None:
        previous_photo_path = employee.photo_path
        employee.photo_path = _save_photo_bytes(photo_bytes, photo_suffix)
        _remove_photo_file(previous_photo_path)

    employee.last_name = payload.last_name
    employee.first_name = payload.first_name
    employee.middle_name = payload.middle_name
    employee.phone = payload.phone
    employee.birth_date = payload.birth_date
    employee.sex = payload.sex

    db.commit()
    return RedirectResponse(url="/employees", status_code=303)


@router.post("/employees/{employee_id}/delete")
def employee_delete(
    employee_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    employee = db.get(Employee, employee_id)
    if employee is not None:
        _remove_photo_file(employee.photo_path)
        db.delete(employee)
        db.commit()
    return RedirectResponse(url="/employees", status_code=303)
