from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.db import SessionLocal
from app.employees import settings as employee_settings
from app.main import app
from app.models import Employee


def _birth_date_for_age(age: int) -> date:
    today = date.today()
    day = min(today.day, 28)
    return date(today.year - age, today.month, day)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (8, 8), (255, 0, 0))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _create_employee(
    *,
    last_name: str,
    first_name: str,
    middle_name: str | None,
    phone: str,
    age: int,
    sex: str,
    photo_path: str | None = None,
) -> int:
    db = SessionLocal()
    employee = Employee(
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        phone=phone,
        birth_date=_birth_date_for_age(age),
        sex=sex,
        photo_path=photo_path,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    employee_id = employee.id
    db.close()
    return employee_id


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state() -> None:
    media_dir = Path(employee_settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    baseline = {file.name for file in media_dir.iterdir() if file.is_file()}

    db = SessionLocal()
    db.query(Employee).delete()
    db.commit()
    db.close()

    yield

    db = SessionLocal()
    db.query(Employee).delete()
    db.commit()
    db.close()

    for file in media_dir.iterdir():
        if file.is_file() and file.name not in baseline:
            file.unlink()


def test_list_search_filters_and_pagination(client: TestClient) -> None:
    _create_employee(
        last_name="Иванов",
        first_name="Петр",
        middle_name="Сергеевич",
        phone="+79990000001",
        age=19,
        sex="male",
    )
    _create_employee(
        last_name="Петрова",
        first_name="Анна",
        middle_name=None,
        phone="+79990000002",
        age=25,
        sex="female",
    )
    for index in range(employee_settings.page_size):
        _create_employee(
            last_name=f"Тест{index}",
            first_name="Сотрудник",
            middle_name=None,
            phone=f"+7999100{index:04d}",
            age=30 + (index % 3),
            sex="male" if index % 2 == 0 else "female",
        )

    response_search = client.get("/employees", params={"search": "иван"})
    assert response_search.status_code == 200
    assert "Иванов Петр Сергеевич" in response_search.text
    assert "Петрова Анна" not in response_search.text

    response_age_search = client.get("/employees", params={"search": "25"})
    assert response_age_search.status_code == 200
    assert "Петрова Анна" in response_age_search.text

    response_male = client.get("/employees", params={"male": "true", "female": "false"})
    assert response_male.status_code == 200
    assert "Петрова Анна" not in response_male.text
    assert "Муж." in response_male.text

    response_invalid_range = client.get("/employees", params={"age_from": "40", "age_to": "20"})
    assert response_invalid_range.status_code == 200
    assert "не может быть больше" in response_invalid_range.text

    response_page_2 = client.get("/employees", params={"page": 2})
    assert response_page_2.status_code == 200
    assert "Страницы:" in response_page_2.text
    assert "Тест0 Сотрудник" not in response_page_2.text


def test_create_employee_success_with_phone_normalization(client: TestClient) -> None:
    response = client.post(
        "/employees/new",
        data={
            "last_name": "Иванов",
            "first_name": "Петр",
            "middle_name": "Сергеевич",
            "phone": "8 (925) 111-22-33",
            "birth_date": "1995-05-10",
            "sex": "male",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/employees"

    db = SessionLocal()
    stored = db.query(Employee).filter(Employee.last_name == "Иванов").one_or_none()
    db.close()
    assert stored is not None
    assert stored.phone == "+79251112233"


def test_create_employee_validation_errors(client: TestClient) -> None:
    response = client.post(
        "/employees/new",
        data={
            "last_name": "",
            "first_name": "123",
            "middle_name": "",
            "phone": "12",
            "birth_date": "2999-01-01",
            "sex": "",
        },
    )
    assert response.status_code == 400
    assert "обязательно" in response.text
    assert "Телефон" in response.text

    db = SessionLocal()
    count = db.query(Employee).count()
    db.close()
    assert count == 0


def test_create_employee_rejects_photo_larger_than_200kb(client: TestClient) -> None:
    large_photo = b"x" * (200 * 1024 + 1)
    response = client.post(
        "/employees/new",
        data={
            "last_name": "Петров",
            "first_name": "Игорь",
            "middle_name": "",
            "phone": "+79990000111",
            "birth_date": "1994-04-04",
            "sex": "male",
        },
        files={"photo": ("large.png", large_photo, "image/png")},
    )
    assert response.status_code == 400
    assert "200 КБ" in response.text

    db = SessionLocal()
    count = db.query(Employee).count()
    db.close()
    assert count == 0


def test_edit_employee_updates_data_and_photo(client: TestClient) -> None:
    employee_id = _create_employee(
        last_name="Сидоров",
        first_name="Олег",
        middle_name=None,
        phone="+79990000222",
        age=30,
        sex="male",
    )

    get_response = client.get(f"/employees/{employee_id}/edit")
    assert get_response.status_code == 200
    assert "Сидоров" in get_response.text

    photo_bytes = _png_bytes()
    post_response = client.post(
        f"/employees/{employee_id}/edit",
        data={
            "last_name": "Сидоров",
            "first_name": "Олег",
            "middle_name": "Олегович",
            "phone": "+79990000222",
            "birth_date": "1994-03-03",
            "sex": "male",
        },
        files={"photo": ("avatar.png", photo_bytes, "image/png")},
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    assert post_response.headers["location"] == "/employees"

    db = SessionLocal()
    updated = db.get(Employee, employee_id)
    db.close()
    assert updated is not None
    assert updated.middle_name == "Олегович"
    assert updated.photo_path is not None
    assert (Path(employee_settings.media_dir) / updated.photo_path).exists()


def test_delete_employee_and_ux_markers(client: TestClient) -> None:
    employee_id = _create_employee(
        last_name="Удаляемый",
        first_name="Сотрудник",
        middle_name=None,
        phone="+79990000333",
        age=20,
        sex="female",
    )

    list_response = client.get("/employees")
    assert list_response.status_code == 200
    assert "return confirm('Вы действительно хотите удалить сотрудника?')" in list_response.text

    form_response = client.get("/employees/new")
    assert form_response.status_code == 200
    assert "type=\"button\" onclick=\"window.location.href='/employees'\"" in form_response.text

    delete_response = client.post(f"/employees/{employee_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/employees"

    db = SessionLocal()
    deleted = db.get(Employee, employee_id)
    db.close()
    assert deleted is None
