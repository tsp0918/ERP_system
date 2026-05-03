"""Human Resources - SQLAlchemy models.

Phase 3 entities (lightweight):
- Department : 部門マスタ (cost-center alignment)
- Employee   : 従業員マスタ
- Assignment : 配属履歴 (employee × department × period)

Note: full SAP HR (SAP HCM / SuccessFactors) is enormous. This minimal
model captures the essentials for ERP integration:
- referencing 'requested_by' / 'approver' on documents
- linking to cost centers (CO module, future)
- retaining audit history of organization changes
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, MasterDataMixin


# ==================================================================
# Department
# ==================================================================
class Department(MasterDataMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("client_id", "department_code",
                         name="uq_departments_client_code"),
    )

    department_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)

    # Logical pointer to a parent department for hierarchical org structure
    parent_department_code: Mapped[Optional[str]] = mapped_column(String(20))

    # Cost center linkage (CO module)
    cost_center_code: Mapped[Optional[str]] = mapped_column(String(20))

    manager_employee_code: Mapped[Optional[str]] = mapped_column(String(20))


# ==================================================================
# Employee
# ==================================================================
class Employee(MasterDataMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("client_id", "employee_code",
                         name="uq_employees_client_code"),
    )

    employee_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # Personal
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)

    # Employment
    company_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    department_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(100))
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    termination_date: Mapped[Optional[date]] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    # ACTIVE / ON_LEAVE / TERMINATED

    # Compensation (sensitive - in real systems goes in a separate restricted table)
    base_salary: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    salary_currency: Mapped[Optional[str]] = mapped_column(String(3))

    # Cost-attribution (CO)
    cost_center_code: Mapped[Optional[str]] = mapped_column(String(20))


# ==================================================================
# Assignment (department history)
# ==================================================================
class Assignment(AuditMixin, Base):
    """Employee × Department over time. New rows on promotion/transfer."""
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    employee_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    department_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    job_title: Mapped[Optional[str]] = mapped_column(String(100))

    valid_from: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31), nullable=False)
