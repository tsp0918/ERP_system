"""Human Resources - REST endpoints."""
from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.hr import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_router import create_crud_router
from app.shared.base_schemas import PaginatedResponse


# ==================================================================
# Departments - generic CRUD
# ==================================================================
dept_router = create_crud_router(
    prefix="/hr/departments",
    tags=["HR - Departments"],
    model=models.Department,
    create_schema=schemas.DepartmentCreate,
    update_schema=schemas.DepartmentUpdate,
    response_schema=schemas.DepartmentResponse,
    resource_name="Department",
)


# ==================================================================
# Employees - custom create (auto-numbering + assignment record)
# ==================================================================
emp_router = APIRouter(prefix="/hr/employees", tags=["HR - Employees"])


@emp_router.get("", response_model=PaginatedResponse[schemas.EmployeeResponse])
def list_employees(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    department_code: str | None = None,
    employment_status: str | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.Employee, db)
    filters = {"department_code": department_code,
              "employment_status": employment_status}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@emp_router.get("/{emp_id}", response_model=schemas.EmployeeResponse)
def get_employee(emp_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    e = BaseRepository(models.Employee, db).get(emp_id, user.client_id)
    if not e:
        raise NotFoundError("Employee", emp_id)
    return e


@emp_router.post("", response_model=schemas.EmployeeResponse,
                 status_code=status.HTTP_201_CREATED)
def create_employee(payload: schemas.EmployeeCreate,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    emp = service.EmployeeService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(emp)
    return emp


@emp_router.put("/{emp_id}", response_model=schemas.EmployeeResponse)
def update_employee(emp_id: int, payload: schemas.EmployeeUpdate,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    repo = BaseRepository(models.Employee, db)
    emp = repo.get(emp_id, user.client_id)
    if not emp:
        raise NotFoundError("Employee", emp_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(emp, data)
    db.commit(); db.refresh(emp)
    return emp


@emp_router.post("/{emp_id}/transfer", response_model=schemas.EmployeeResponse)
def transfer_employee(emp_id: int,
                     new_department_code: str = Body(..., embed=True),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Move an employee to a different department, with assignment history."""
    emp = service.EmployeeService(db).transfer(
        emp_id, new_department_code, user.client_id, user.email)
    db.commit(); db.refresh(emp)
    return emp


def get_hr_routers() -> list[APIRouter]:
    return [dept_router, emp_router]
