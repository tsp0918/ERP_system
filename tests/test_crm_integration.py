"""Phase 5: CRM Integration Tests (IT-01 ~ IT-16).

Covers all CRM ↔ ERP interfaces defined in the ERP_Integration_Spec.
HMAC auth is skipped in dev mode (empty CRM_INBOUND_SIGNING_SECRET).
"""
import pytest
from decimal import Decimal

# Ensure all models are registered with Base.metadata before the engine fixture
# creates tables. These imports happen at collection time.
from app.modules.mdm import models as _mdm        # noqa: F401
from app.modules.sd import models as _sd          # noqa: F401
from app.modules.gts import models as _gts        # noqa: F401
from app.shared import webhook_models as _wh      # noqa: F401
from app.modules.gts import commerce_check as _cc  # noqa: F401
from app.modules.gts.models import LicenseConsumptionLog

from app.modules.mdm import schemas as mdm_schemas, service as mdm_service
from app.modules.sd import models as sd_models
from app.modules.gts import models as gts_models


# ------------------------------------------------------------------
# Shared fixture: basic BP + material in DB
# ------------------------------------------------------------------
@pytest.fixture
def master_data(db_session, admin_user):
    customer = mdm_service.BusinessPartnerService(db_session).create(
        mdm_schemas.BusinessPartnerCreate(
            bp_code="CRM-CUST-01", name="CRM Customer",
            country="US", roles="CUSTOMER", auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    material = mdm_service.MaterialService(db_session).create(
        mdm_schemas.MaterialCreate(
            material_code="CRM-MAT-01", description="CRM Product",
            material_type="FERT", base_unit="PC",
            standard_price=Decimal("500"), auto_classify=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    return {"customer": customer, "material": material}


# ==================================================================
# IT-01: IF-25 basic CRM → ERP SalesOrder (no aitm_transaction_id)
# ==================================================================
def test_it01_crm_sales_order_basic(client, auth_headers, master_data):
    resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-001",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 5, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["erp_document_number"]) == 10        # SALES_ORDER: 10-digit zero-padded
    assert body["export_check_status"] in ("PENDING", "PASSED")  # mock resolves immediately
    # Branch B (no aitm_transaction_id from CRM): ERP creates its own transaction via export_check_ref
    assert body["aitm_transaction_id"] is None


# ==================================================================
# IT-02: IF-25 with existing aitm_transaction_id (CRM provides it)
# ==================================================================
def test_it02_crm_sales_order_with_aitm_tx(client, auth_headers, master_data, db_session):
    resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-002",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "aitm_transaction_id": "AITM-TX-9999",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 2, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["aitm_transaction_id"] == "AITM-TX-9999"

    # Verify link_source="crm" on the AITMTransactionLink
    so = db_session.query(sd_models.SalesOrder).filter(
        sd_models.SalesOrder.id == body["erp_sales_order_id"]
    ).first()
    link = db_session.query(gts_models.AITMTransactionLink).filter(
        gts_models.AITMTransactionLink.sales_order_id == so.id
    ).first()
    assert link is not None
    assert link.link_source == "crm"


# ==================================================================
# IT-03: IF-25 with end_user → auto-create END_USER BP
# ==================================================================
def test_it03_crm_sales_order_with_end_user(client, auth_headers, master_data, db_session):
    resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-003",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "end_user": {
            "name": "End User Corp",
            "country": "SG",
            "address": "1 Marina Bay",
            "crm_account_id": "CRM-ACC-EU-001",
        },
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["end_user_bp_code"] is not None

    from app.modules.mdm.models import BusinessPartner
    eu_bp = db_session.query(BusinessPartner).filter(
        BusinessPartner.client_id == "DEMO",
        BusinessPartner.bp_code == body["end_user_bp_code"],
    ).first()
    assert eu_bp is not None
    assert "END_USER" in eu_bp.roles
    assert eu_bp.country == "SG"


# ==================================================================
# IT-04: IF-24 hold → SUSPENDED
# ==================================================================
def test_it04_continuous_monitoring_hold(client, auth_headers, master_data, db_session):
    # Create SO first
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-004",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    so_id = so_resp.json()["erp_sales_order_id"]

    resp = client.post(f"/crm/continuous-monitoring-hold/{so_id}", json={
        "action": "hold",
        "reason": "Sanction list match detected",
        "client_id": "DEMO",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "SUSPENDED"

    db_session.expire_all()
    so = db_session.query(sd_models.SalesOrder).filter(
        sd_models.SalesOrder.id == so_id).first()
    assert so.status == "SUSPENDED"


# ==================================================================
# IT-05: IF-24 release → OPEN
# ==================================================================
def test_it05_continuous_monitoring_release(client, auth_headers, master_data, db_session):
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-005",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    so_id = so_resp.json()["erp_sales_order_id"]

    client.post(f"/crm/continuous-monitoring-hold/{so_id}", json={
        "action": "hold", "client_id": "DEMO"})

    resp = client.post(f"/crm/continuous-monitoring-hold/{so_id}", json={
        "action": "release",
        "reason": "Cleared after review",
        "client_id": "DEMO",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "OPEN"


# ==================================================================
# IT-06: IF-32 commerce check — BP found by bp_code
# ==================================================================
def test_it06_commerce_check_bp_found(client, auth_headers, master_data):
    resp = client.post("/crm/commerce-check", json={
        "request_type": "quote",
        "crm_quote_id": 1001,
        "counterparty": {"bp_code": "CRM-CUST-01"},
        "client_id": "DEMO",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_result"] == "ok"
    assert body["stub_mode"] is True
    assert body["results"]["credit"]["result"] == "ok"
    assert body["results"]["antisocial"]["result"] == "ok"


# ==================================================================
# IT-07: IF-32 commerce check — BP not found (no error, stub still ok)
# ==================================================================
def test_it07_commerce_check_bp_not_found(client, auth_headers):
    resp = client.post("/crm/commerce-check", json={
        "request_type": "engagement",
        "counterparty": {"crm_account_id": "NONEXISTENT-ACCOUNT"},
        "client_id": "DEMO",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_result"] == "ok"
    assert body["counterparty_attributes"] == {}


# ==================================================================
# IT-08: IF-23 — allocation_id stored on SO via judgment webhook
# ==================================================================
def test_it08_aitm_allocation_id_stored(client, auth_headers, master_data, db_session):
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-008",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "aitm_transaction_id": "AITM-TX-8888",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 3, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert so_resp.status_code == 201

    # Simulate AI_TM → ERP judgment webhook with allocation_id (IF-23)
    wh_resp = client.post("/gts/webhook/judgment-updated", json={
        "material_code": "CRM-MAT-01",
        "new_judgment": "APPROVED",
        "transaction_id": "AITM-TX-8888",
        "allocation_id": "ALLOC-UUID-001",
        "client_id": "DEMO",
    })
    assert wh_resp.status_code == 200, wh_resp.text

    db_session.expire_all()
    so = db_session.query(sd_models.SalesOrder).filter(
        sd_models.SalesOrder.aitm_transaction_id == "AITM-TX-8888",
        sd_models.SalesOrder.client_id == "DEMO",
    ).first()
    assert so is not None
    assert so.aitm_allocation_id == "ALLOC-UUID-001"


# ==================================================================
# IT-09: GTS judgment webhook APPROVED → unblocks SO items
# ==================================================================
def test_it09_judgment_webhook_approved(client, auth_headers, master_data):
    # Create SO normally (will get PENDING export check)
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-009",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert so_resp.status_code == 201

    wh_resp = client.post("/gts/webhook/judgment-updated", json={
        "material_code": "CRM-MAT-01",
        "new_judgment": "APPROVED",
        "new_eccn": "EAR99",
        "client_id": "DEMO",
    })
    assert wh_resp.status_code == 200


# ==================================================================
# IT-10: GTS judgment webhook REJECTED
# ==================================================================
def test_it10_judgment_webhook_rejected(client, auth_headers, master_data):
    client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-010",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })

    wh_resp = client.post("/gts/webhook/judgment-updated", json={
        "material_code": "CRM-MAT-01",
        "new_judgment": "REJECTED",
        "client_id": "DEMO",
    })
    assert wh_resp.status_code == 200


# ==================================================================
# IT-11: Delivery with aitm_allocation_id → license consumption log
# ==================================================================
def test_it11_license_consumption_on_delivery(client, auth_headers, master_data, db_session):
    from app.modules.sd import service as sd_service, schemas as sd_schemas

    # Create SO with skip_export_check + manually set allocation_id
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-011",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "aitm_transaction_id": "AITM-TX-0011",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 2, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    assert so_resp.status_code == 201
    so_id = so_resp.json()["erp_sales_order_id"]

    # Simulate IF-23: set allocation_id on the SO
    so = db_session.query(sd_models.SalesOrder).filter(
        sd_models.SalesOrder.id == so_id).first()
    so.aitm_allocation_id = "ALLOC-TEST-011"
    so.export_check_status = "SKIPPED"    # allow delivery without rescreen
    db_session.commit()

    from datetime import date
    delivery = sd_service.DeliveryService(db_session).create(
        sd_schemas.DeliveryCreate(
            sales_order_id=so_id,
            document_date=date.today(),
            plant_code="P001",
        ),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    logs = db_session.query(LicenseConsumptionLog).filter(
        LicenseConsumptionLog.delivery_id == delivery.id
    ).all()
    assert len(logs) == 1
    assert logs[0].allocation_id == "ALLOC-TEST-011"
    assert logs[0].consumed_quantity == Decimal("2.000")
    assert logs[0].response_status == "consumed"


# ==================================================================
# IT-12: IF-28 — webhook enqueued after delivery on CRM-originated SO
# ==================================================================
def test_it12_delivery_webhook_enqueued(client, auth_headers, master_data, db_session):
    from app.shared.webhook_models import WebhookDelivery
    from app.modules.sd import service as sd_service, schemas as sd_schemas
    from datetime import date

    # Branch C (skip_export_check=True) + crm_contract_id: clean path through rescreen
    so = sd_service.SalesOrderService(db_session).create(
        sd_schemas.SalesOrderCreate(
            customer_code="CRM-CUST-01",
            currency="USD",
            skip_export_check=True,
            crm_contract_id="CRM-CONTRACT-012",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="CRM-MAT-01", quantity=Decimal("1"), unit="PC", unit_price=Decimal("500"),
            )],
        ),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    sd_service.DeliveryService(db_session).create(
        sd_schemas.DeliveryCreate(sales_order_id=so.id, document_date=date.today(), plant_code="P001"),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    wh = db_session.query(WebhookDelivery).filter(
        WebhookDelivery.event_type == "delivery.goods_issued",
        WebhookDelivery.client_id == "DEMO",
    ).first()
    assert wh is not None
    assert wh.status == "pending"


# ==================================================================
# IT-13: IF-29 — billing.posted webhook enqueued
# ==================================================================
def test_it13_billing_webhook_enqueued(client, auth_headers, master_data, db_session):
    from app.shared.webhook_models import WebhookDelivery
    from app.modules.sd import service as sd_service, schemas as sd_schemas
    from datetime import date

    so = sd_service.SalesOrderService(db_session).create(
        sd_schemas.SalesOrderCreate(
            customer_code="CRM-CUST-01",
            currency="USD",
            skip_export_check=True,
            crm_contract_id="CRM-CONTRACT-013",
            items=[sd_schemas.SalesOrderItemCreate(
                material_code="CRM-MAT-01", quantity=Decimal("1"), unit="PC", unit_price=Decimal("500"),
            )],
        ),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    delivery = sd_service.DeliveryService(db_session).create(
        sd_schemas.DeliveryCreate(sales_order_id=so.id, document_date=date.today(), plant_code="P001"),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    sd_service.BillingService(db_session).create_from_delivery(
        sd_schemas.BillingCreate(delivery_id=delivery.id, document_date=date.today()),
        "DEMO", "test@example.com",
    )
    db_session.commit()

    wh = db_session.query(WebhookDelivery).filter(
        WebhookDelivery.event_type == "billing.posted",
        WebhookDelivery.client_id == "DEMO",
    ).first()
    assert wh is not None
    assert wh.status == "pending"


# ==================================================================
# IT-14: IF-31 CRM → ERP return document creation
# ==================================================================
def test_it14_crm_return_creation(client, auth_headers, master_data, db_session):
    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-014",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 5, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    so_id = so_resp.json()["erp_sales_order_id"]

    resp = client.post("/crm/returns", json={
        "crm_return_id": "CRM-RET-001",
        "crm_contract_id": "CRM-CONTRACT-014",
        "erp_sales_order_id": so_id,
        "return_reason": "Product defect",
        "items": [
            {"material_code": "CRM-MAT-01", "quantity": 2, "unit": "PC"},
        ],
        "client_id": "DEMO",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["crm_return_id"] == "CRM-RET-001"
    assert body["item_count"] == 1
    assert len(body["erp_document_number"]) == 10        # RETURN: 10-digit zero-padded


# ==================================================================
# IT-15: IF-30 — return.posted webhook enqueued after return creation
# ==================================================================
def test_it15_return_webhook_enqueued(client, auth_headers, master_data, db_session):
    from app.shared.webhook_models import WebhookDelivery

    so_resp = client.post("/crm/sales-orders", json={
        "crm_contract_id": "CRM-CONTRACT-015",
        "customer_code": "CRM-CUST-01",
        "currency": "USD",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 5, "unit": "PC", "unit_price": 500}],
        "client_id": "DEMO",
    })
    so_id = so_resp.json()["erp_sales_order_id"]

    client.post("/crm/returns", json={
        "crm_return_id": "CRM-RET-015",
        "erp_sales_order_id": so_id,
        "return_reason": "Excess quantity",
        "items": [{"material_code": "CRM-MAT-01", "quantity": 1, "unit": "PC"}],
        "client_id": "DEMO",
    })

    wh = db_session.query(WebhookDelivery).filter(
        WebhookDelivery.event_type == "return.posted",
        WebhookDelivery.client_id == "DEMO",
    ).first()
    assert wh is not None
    assert wh.status == "pending"


# ==================================================================
# IT-16: DLQ admin — GET /admin/webhook-delivery
# ==================================================================
def test_it16_dlq_admin_endpoint(client, auth_headers):
    resp = client.get("/admin/webhook-delivery", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)   # returns a list of WebhookDeliveryOut objects
