from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("sex IN ('male', 'female')", name="ck_employees_sex"),
        CheckConstraint("length(last_name) > 0", name="ck_employees_last_name_not_empty"),
        CheckConstraint("length(first_name) > 0", name="ck_employees_first_name_not_empty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sex: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return " ".join(parts)

    def calculate_age(self, on_date: date | None = None) -> int:
        today = on_date or date.today()
        years = today.year - self.birth_date.year
        has_had_birthday = (today.month, today.day) >= (self.birth_date.month, self.birth_date.day)
        return years if has_had_birthday else years - 1
