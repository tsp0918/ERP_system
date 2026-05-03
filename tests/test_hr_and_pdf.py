"""Tests for HR module and Invoice PDF generator."""
import pytest
from datetime import date
from decimal import Decimal

from app.modules.hr import schemas as hr_schemas
from app.modules.hr.service import DepartmentService, EmployeeService


# ==================================================================
# HR
# ==================================================================
def test_create_department(db_session, admin_user):
    d = DepartmentService(db_session).create(
        hr_schemas.DepartmentCreate(
            department_code="ENG", name="Engineering",
            company_code="1000",
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert d.department_code == "ENG"
    assert d.is_active is True


def test_create_employee_with_auto_code(db_session, admin_user):
    DepartmentService(db_session).create(
        hr_schemas.DepartmentCreate(
            department_code="ENG", name="Engineering"),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    e = EmployeeService(db_session).create(
        hr_schemas.EmployeeCreate(
            first_name="Test", last_name="User",
            company_code="1000", department_code="ENG",
            job_title="Engineer", hire_date=date(2024, 1, 1),
            base_salary=Decimal("6000000"), salary_currency="JPY",
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert e.employee_code.startswith("EMP-")
    assert e.first_name == "Test"


def test_employee_transfer_creates_assignment_history(db_session, admin_user):
    """Transferring an employee creates a new assignment row and closes the old one."""
    dept_svc = DepartmentService(db_session)
    dept_svc.create(hr_schemas.DepartmentCreate(
        department_code="A", name="A"), admin_user.client_id, admin_user.email)
    dept_svc.create(hr_schemas.DepartmentCreate(
        department_code="B", name="B"), admin_user.client_id, admin_user.email)
    db_session.commit()

    emp_svc = EmployeeService(db_session)
    e = emp_svc.create(hr_schemas.EmployeeCreate(
        first_name="T", last_name="U", department_code="A",
    ), admin_user.client_id, admin_user.email)
    db_session.commit()

    # Initial assignment
    from app.modules.hr.models import Assignment
    assignments = db_session.query(Assignment).filter(
        Assignment.employee_code == e.employee_code,
    ).all()
    assert len(assignments) == 1
    assert assignments[0].department_code == "A"

    # Transfer to B
    emp_svc.transfer(e.id, "B", admin_user.client_id, admin_user.email)
    db_session.commit()
    db_session.refresh(e)
    assert e.department_code == "B"

    assignments = db_session.query(Assignment).filter(
        Assignment.employee_code == e.employee_code,
    ).order_by(Assignment.id).all()
    assert len(assignments) == 2
    # First assignment should be closed (valid_to != end-of-time)
    assert assignments[0].valid_to != date(2099, 12, 31)
    # Second is the open one
    assert assignments[1].department_code == "B"
    assert assignments[1].valid_to == date(2099, 12, 31)


# ==================================================================
# Invoice PDF generator
# ==================================================================
@pytest.fixture
def billing_for_pdf(db_session, admin_user):
    """Set up a billing + customer + seller for PDF rendering."""
    from app.modules.mdm.models import BusinessPartner, Company
    from app.modules.sd.models import BillingDocument, BillingItem

    seller = Company(
        client_id=admin_user.client_id,
        company_code="1000",
        name="Test Seller K.K.",
        country="JP",
        currency="JPY",
        created_by=admin_user.email,
        updated_by=admin_user.email,
    )
    customer = BusinessPartner(
        client_id=admin_user.client_id,
        bp_code="BP-CUST",
        name="Test Customer Inc.",
        country="US",
        roles="CUSTOMER",
        address_line1="100 Main St",
        city="Hillsboro",
        postal_code="97124",
        currency="USD",
        payment_terms="NET30",
        created_by=admin_user.email,
        updated_by=admin_user.email,
    )
    bill = BillingDocument(
        client_id=admin_user.client_id,
        document_number="0090001234",
        document_date=date(2026, 4, 28),
        status="OPEN",
        customer_code="BP-CUST",
        currency="USD",
        net_amount=Decimal("1500.00"),
        tax_amount=Decimal("0.00"),
        gross_amount=Decimal("1500.00"),
        payment_terms="NET30",
    )
    bill.items.append(BillingItem(
        item_no=10, material_code="MAT-X",
        quantity=Decimal("10"),
        unit_price=Decimal("150"),
        net_amount=Decimal("1500"),
        created_by=admin_user.email, updated_by=admin_user.email,
    ))
    db_session.add_all([seller, customer, bill])
    db_session.commit()
    db_session.refresh(bill)
    return {"seller": seller, "customer": customer, "billing": bill}


@pytest.mark.parametrize("variant", ["intercompany", "distributor", "enduser"])
def test_pdf_generator_outputs_valid_pdf(billing_for_pdf, variant):
    """Each variant produces a non-trivial PDF with the standard header."""
    from app.modules.sd.invoice_pdf import InvoicePdfGenerator

    pdf = InvoicePdfGenerator(variant=variant).render(
        billing=billing_for_pdf["billing"],
        customer=billing_for_pdf["customer"],
        seller_company=billing_for_pdf["seller"],
        material_descriptions={"MAT-X": "Test Product"},
    )
    # Sanity: PDF magic header + non-trivial size
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_pdf_generator_unknown_variant_rejected():
    from app.modules.sd.invoice_pdf import InvoicePdfGenerator
    with pytest.raises(ValueError):
        InvoicePdfGenerator(variant="garbage")
