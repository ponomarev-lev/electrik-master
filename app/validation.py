from __future__ import annotations

from datetime import date
import re
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError


MAX_PHOTO_SIZE_BYTES = 200 * 1024
ALLOWED_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁё]+$")
LAST_NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*$")


def _required_text(value: str | None, field_label: str) -> str:
    if value is None:
        raise ValueError(f"Поле '{field_label}' обязательно.")
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ValueError(f"Поле '{field_label}' обязательно.")
    return cleaned


def validate_last_name(value: str | None) -> str:
    cleaned = _required_text(value, "Фамилия")
    if len(cleaned) > 100:
        raise ValueError("Фамилия должна быть не длиннее 100 символов.")
    if not LAST_NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("Фамилия может содержать только буквы и дефис.")
    return cleaned


def validate_first_name(value: str | None) -> str:
    cleaned = _required_text(value, "Имя")
    if len(cleaned) > 100:
        raise ValueError("Имя должно быть не длиннее 100 символов.")
    if not NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("Имя может содержать только буквы.")
    return cleaned


def validate_middle_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    if len(cleaned) > 100:
        raise ValueError("Отчество должно быть не длиннее 100 символов.")
    if not NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("Отчество может содержать только буквы.")
    return cleaned


def normalize_phone(value: str | None) -> str:
    cleaned = _required_text(value, "Телефон")
    digits = re.sub(r"\D", "", cleaned)

    if len(digits) == 10:
        digits = f"7{digits}"
    elif len(digits) == 11 and digits[0] in {"7", "8"}:
        digits = f"7{digits[1:]}"
    else:
        raise ValueError("Телефон должен быть в формате +7XXXXXXXXXX.")

    return f"+{digits}"


def parse_birth_date(value: str | date | None) -> date:
    if value is None:
        raise ValueError("Поле 'Дата рождения' обязательно.")

    if isinstance(value, date):
        birth_date = value
    else:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Поле 'Дата рождения' обязательно.")
        try:
            birth_date = date.fromisoformat(cleaned)
        except ValueError as error:
            raise ValueError("Дата рождения должна быть в формате ГГГГ-ММ-ДД.") from error

    if birth_date > date.today():
        raise ValueError("Дата рождения не может быть больше текущей даты.")

    return birth_date


def validate_sex(value: str | None) -> str:
    cleaned = _required_text(value, "Пол")
    if cleaned not in {"male", "female"}:
        raise ValueError("Нужно выбрать корректное значение пола.")
    return cleaned


async def read_and_validate_photo(upload: UploadFile | None) -> tuple[bytes | None, str | None]:
    if upload is None or not upload.filename:
        return None, None

    suffix = Path(upload.filename).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_PHOTO_EXTENSIONS:
        raise ValueError("Фото должно быть в формате jpg, jpeg, png или webp.")

    if upload.content_type not in ALLOWED_PHOTO_CONTENT_TYPES:
        raise ValueError("Недопустимый MIME-тип файла изображения.")

    raw = await upload.read(MAX_PHOTO_SIZE_BYTES + 1)
    await upload.seek(0)

    if len(raw) > MAX_PHOTO_SIZE_BYTES:
        raise ValueError("Размер фото должен быть не больше 200 КБ.")

    if not raw:
        raise ValueError("Файл фото пустой.")

    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Загруженный файл не является корректным изображением.") from error

    return raw, suffix
