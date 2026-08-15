"""Tests for Sales & Distribution end-to-end flow."""
import pytest
from decimal import Decimal

from app.modules.mdm import schemas as mdm_schemas, service as mdm_service
from app.modules.sd import schemas as sd_schemas, service as sd_service


@pytest.fixture
def basic_master_data(db_session, admin_user):
    """Create one customer and one material."""
    customer = mdm_service.BusinessPartnerService(db_session).create(
        mdm_schemas.BusinessPartnerCreate(
            bp_code="BP-CUST-1", name="Test Customer",
            country="JP", roles="CUSTOMER", auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    material = mdm_service.MaterialService(db_session).create(
        mdm_schemas.MaterialCreate(
            material_code="MAT-TEST-1", description="Test Product",
            material_type="FERT", base_unit="L",
            standard_price=Decimal("100"), auto_classify=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    return {"customer": customer, "material": material}


def test_create_sales_order(db_session, admin_user, basic_master_data):
    so = sd_service.SalesOrderService(db_session).create(
        sd_schemas.SalesOrderCreate(
            customer_code="BP-CUST-1",
            currency="JPY",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="MAT-TEST-1",
                quantity=Decimal("10"),
                unit="L",
                unit_price=Decimal("100"),
            )],
            skip_export_check=True,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(so)
    assert so.document_number is not None
    assert len(so.items) == 1
    assert so.total_amount == Decimal("1000.00")
    # skip_export_check=True → status is SKIPPED (not checked; downstream shipment passes without rescreen)
    assert so.export_check_status == "SKIPPED"


def test_sales_order_export_check_blocks_restricted_country(
    db_session, admin_user, basic_master_data,
):
    """Customer in IR (restricted) -> SO becomes BLOCKED."""
    # Make customer's country IR
    customer = basic_master_data["customer"]
    customer.country = "IR"
    db_session.commit()

    so = sd_service.SalesOrderService(db_session).create(
        sd_schemas.SalesOrderCreate(
            customer_code="BP-CUST-1",
            currency="JPY",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="MAT-TEST-1",
                quantity=Decimal("1"),
                unit="L",
                unit_price=Decimal("100"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(so)
    assert so.export_check_status == "BLOCKED"
    assert so.status == "BLOCKED"


def test_blocked_so_cannot_be_released(db_session, admin_user, basic_master_data):
    customer = basic_master_data["customer"]
    customer.country = "IR"
    db_session.commit()

    svc = sd_service.SalesOrderService(db_session)
    so = svc.create(
        sd_schemas.SalesOrderCreate(
            customer_code="BP-CUST-1", currency="JPY",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="MAT-TEST-1", quantity=Decimal("1"),
                unit="L", unit_price=Decimal("100"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    with pytest.raises(Exception):  # BusinessRuleError
        svc.release(so.id, admin_user.client_id, admin_user.email)


def test_full_order_to_cash(db_session, admin_user, basic_master_data):
    """SO → Delivery → Billing happy path."""
    so_svc = sd_service.SalesOrderService(db_session)
    delivery_svc = sd_service.DeliveryService(db_session)
    bill_svc = sd_service.BillingService(db_session)

    # 1. Create SO (skip export check for this test)
    so = so_svc.create(
        sd_schemas.SalesOrderCreate(
            customer_code="BP-CUST-1", currency="JPY",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="MAT-TEST-1", quantity=Decimal("10"),
                unit="L", unit_price=Decimal("100"),
            )],
            skip_export_check=True,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # 2. Release
    so_svc.release(so.id, admin_user.client_id, admin_user.email)
    db_session.commit()

    # 3. Delivery (full)
    delivery = delivery_svc.create(
        sd_schemas.DeliveryCreate(sales_order_id=so.id),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert len(delivery.items) == 1
    assert delivery.items[0].quantity == Decimal("10")

    # 4. Billing
    bill = bill_svc.create_from_delivery(
        sd_schemas.BillingCreate(delivery_id=delivery.id),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(bill)
    assert bill.net_amount == Decimal("1000.00")
    assert bill.gross_amount == Decimal("1000.00")
    assert len(bill.items) == 1


def test_invalid_customer_rejected(db_session, admin_user, basic_master_data):
    with pytest.raises(Exception):
        sd_service.SalesOrderService(db_session).create(
            sd_schemas.SalesOrderCreate(
                customer_code="BP-NONEXISTENT",
                currency="JPY",
                items=[sd_schemas.SalesOrderItemCreate(
                    material_code="MAT-TEST-1", quantity=Decimal("1"),
                    unit="L", unit_price=Decimal("100"),
                )],
                skip_export_check=True,
            ),
            admin_user.client_id, admin_user.email,
        )


def test_vendor_role_cannot_be_customer(db_session, admin_user, basic_master_data):
    """A BP without CUSTOMER role cannot be used on a sales order."""
    vendor_only = mdm_service.BusinessPartnerService(db_session).create(
        mdm_schemas.BusinessPartnerCreate(
            bp_code="BP-VEND-1", name="V", country="JP",
            roles="VENDOR", auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    with pytest.raises(Exception):
        sd_service.SalesOrderService(db_session).create(
            sd_schemas.SalesOrderCreate(
                customer_code="BP-VEND-1", currency="JPY",
                items=[sd_schemas.SalesOrderItemCreate(
                    material_code="MAT-TEST-1", quantity=Decimal("1"),
                    unit="L", unit_price=Decimal("100"),
                )],
                skip_export_check=True,
            ),
            admin_user.client_id, admin_user.email,
        )
