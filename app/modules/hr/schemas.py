"""Human Resources - Pydantic schemas."""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.shared.base_schemas import AuditFields, ORMModel


# ==================================================================
# Department
# ==================================================================
class DepartmentBase(BaseModel):
    department_code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    company_code: Optional[str] = None
    parent_department_code: Optional[str] = None
    cost_center_code: Optional[str] = None
    manager_employee_code: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    parent_department_code: Optional[str] = None
    cost_center_code: Optional[str] = None
    manager_employee_code: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentResponse(DepartmentBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Employee
# ==================================================================
class EmployeeBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    email: Optional[str] = None
    company_code: Optional[str] = None
    department_code: Optional[str] = None
    job_title: Optional[str] = None
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None
    employment_status: str = Field("ACTIVE",
                                  description="ACTIVE / ON_LEAVE / TERMINATED")
    base_salary: Optional[Decimal] = None
    salary_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    cost_center_code: Optional[str] = None


class EmployeeCreate(EmployeeBase):
    employee_code: Optional[str] = Field(None, max_length=20,
        description="If omitted, auto-generated as EMP-XXXXXXX")


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    department_code: Optional[str] = None
    job_title: Optional[str] = None
    employment_status: Optional[str] = None
    base_salary: Optional[Decimal] = None
    cost_center_code: Optional[str] = None
    is_active: Optional[bool] = None
    termination_date: Optional[date] = None


class EmployeeResponse(EmployeeBase, AuditFields):
    id: int
    employee_code: str
    is_active: bool

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
