"""Tests for Master Data Management."""
import pytest
from decimal import Decimal

from app.modules.mdm import schemas, service


# ==================================================================
# Company
# ==================================================================
def test_create_company(db_session, admin_user):
    co = service.CompanyService(db_session).create(
        schemas.CompanyCreate(
            company_code="9999", name="Test Co Ltd",
            country="JP", currency="JPY",
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert co.company_code == "9999"
    assert co.is_active is True
    assert co.created_by == admin_user.email


def test_company_duplicate_code_rejected(db_session, admin_user):
    svc = service.CompanyService(db_session)
    svc.create(
        schemas.CompanyCreate(company_code="9999", name="A",
                              country="JP", currency="JPY"),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    with pytest.raises(Exception):
        svc.create(
            schemas.CompanyCreate(company_code="9999", name="B",
                                  country="JP", currency="JPY"),
            admin_user.client_id, admin_user.email,
        )


# ==================================================================
# Material
# ==================================================================
def test_create_material_with_auto_code(db_session, admin_user):
    m = service.MaterialService(db_session).create(
        schemas.MaterialCreate(
            description="Test Material",
            material_type="ROH",
            base_unit="KG",
            standard_price=Decimal("1500"),
            currency="JPY",
            country_of_origin="JP",
            auto_classify=False,  # don't trigger AI_TM in unit test
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert m.material_code.startswith("MAT-")
    assert m.fefta_judgment == "UNKNOWN"
    assert m.is_active is True


def test_create_material_with_explicit_code(db_session, admin_user):
    m = service.MaterialService(db_session).create(
        schemas.MaterialCreate(
            material_code="MAT-CUSTOM-1",
            description="Custom Material",
            material_type="FERT",
            auto_classify=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert m.material_code == "MAT-CUSTOM-1"


def test_material_auto_classify_via_mock(db_session, admin_user):
    """When auto_classify=True, the mock AI_TM client populates HS/ECCN."""
    m = service.MaterialService(db_session).create(
        schemas.MaterialCreate(
            description="High Purity Silane Gas SiH4 6N",  # matches CONTROLLED_KEYWORDS
            material_type="ROH",
            auto_classify=True,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(m)
    # The mock should have fired: silane matches CONTROLLED keyword
    assert m.fefta_judgment == "APPLICABLE"
    assert m.eccn == "3C001"
    assert m.hs_code is not None


# ==================================================================
# BusinessPartner
# ==================================================================
def test_create_business_partner_customer(db_session, admin_user):
    bp = service.BusinessPartnerService(db_session).create(
        schemas.BusinessPartnerCreate(
            name="Test Customer", country="JP", roles="CUSTOMER",
            auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert bp.bp_code.startswith("BP-")
    assert bp.has_role("CUSTOMER") is True
    assert bp.has_role("VENDOR") is False
    assert bp.is_denied_party is False


def test_business_partner_multiple_roles(db_session, admin_user):
    bp = service.BusinessPartnerService(db_session).create(
        schemas.BusinessPartnerCreate(
            name="Both Roles", country="JP", roles="CUSTOMER,VENDOR",
            auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert bp.has_role("CUSTOMER") is True
    assert bp.has_role("VENDOR") is True


def test_business_partner_screening_flags_restricted_country(db_session, admin_user):
    bp = service.BusinessPartnerService(db_session).create(
        schemas.BusinessPartnerCreate(
            name="Iran Partner", country="IR", roles="CUSTOMER",
            auto_screen=True,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(bp)
    assert bp.is_denied_party is True


# ==================================================================
# REST API endpoints
# ==================================================================
def test_list_materials_requires_auth(client):
    r = client.get("/mdm/materials")
    assert r.status_code == 401


def test_list_materials_empty(client, auth_headers):
    r = client.get("/mdm/materials", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_create_material_via_api(client, auth_headers):
    r = client.post("/mdm/materials", headers=auth_headers, json={
        "description": "Test Item", "material_type": "ROH",
        "base_unit": "KG", "auto_classify": False,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["description"] == "Test Item"
    assert body["material_code"].startswith("MAT-")


def test_create_material_validation_error(client, auth_headers):
    r = client.post("/mdm/materials", headers=auth_headers, json={
        # description is required
        "material_type": "ROH",
    })
    assert r.status_code == 422
