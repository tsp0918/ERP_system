"""Human Resources - business logic.

Lightweight: master data CRUD plus assignment history tracking.
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateError, NotFoundError
from app.core.numbering import next_number
from app.modules.hr import models, schemas
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def _seed_hr_ranges() -> None:
    from app.core.numbering import DEFAULT_RANGES
    DEFAULT_RANGES.setdefault(
        "EMPLOYEE", {"prefix": "EMP-", "width": 7, "start": 1})


# ==================================================================
# Department
# ==================================================================
class DepartmentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.Department, db)

    def create(self, payload: schemas.DepartmentCreate, client_id: str,
               user_email: str) -> models.Department:
        existing = self.repo.get_by_field(
            "department_code", payload.department_code, client_id)
        if existing:
            raise DuplicateError("Department", "department_code",
                                payload.department_code)
        data = payload.model_dump()
        data.update({"client_id": client_id, "created_by": user_email,
                    "updated_by": user_email})
        return self.repo.create(data)


# ==================================================================
# Employee
# ==================================================================
class EmployeeService:
    def __init__(self, db: Session):
        self.db = db
        _seed_hr_ranges()
        self.repo = BaseRepository(models.Employee, db)

    def create(self, payload: schemas.EmployeeCreate, client_id: str,
               user_email: str) -> models.Employee:
        emp_code = payload.employee_code or next_number(
            self.db, client_id, "EMPLOYEE")
        existing = self.repo.get_by_field("employee_code", emp_code, client_id)
        if existing:
            raise DuplicateError("Employee", "employee_code", emp_code)

        data = payload.model_dump(exclude={"employee_code"})
        data.update({
            "employee_code": emp_code,
            "client_id": client_id,
            "created_by": user_email, "updated_by": user_email,
        })
        emp = self.repo.create(data)

        # Record assignment history if department is given
        if emp.department_code:
            self._add_assignment(emp, user_email)

        return emp

    def transfer(self, employee_id: int, new_department_code: str,
                 client_id: str, user_email: str) -> models.Employee:
        """Transfer an employee to a new department, closing the prior assignment."""
        emp = self.repo.get(employee_id, client_id)
        if not emp:
            raise NotFoundError("Employee", employee_id)

        # Close current open assignment
        today = date.today()
        current = self.db.query(models.Assignment).filter(
            models.Assignment.client_id == client_id,
            models.Assignment.employee_code == emp.employee_code,
            models.Assignment.valid_to == date(2099, 12, 31),
        ).first()
        if current and current.department_code != new_department_code:
            current.valid_to = today

        # Update employee record
        emp.department_code = new_department_code
        emp.updated_by = user_email

        # Open new assignment
        self._add_assignment(emp, user_email)
        return emp

    def _add_assignment(self, emp: models.Employee, user_email: str):
        a = models.Assignment(
            client_id=emp.client_id,
            employee_code=emp.employee_code,
            department_code=emp.department_code,
            job_title=emp.job_title,
            valid_from=date.today(),
            valid_to=date(2099, 12, 31),
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(a)
        self.db.flush()
