"""Tests for shared infrastructure: BaseRepository, Document mixins."""
from app.modules.mdm.models import Material
from app.shared.base_repository import BaseRepository


def test_base_repo_create_and_get(db_session, admin_user):
    repo = BaseRepository(Material, db_session)
    instance = repo.create({
        "client_id": admin_user.client_id,
        "material_code": "MAT-REPO-1",
        "description": "Test",
        "material_type": "ROH",
        "base_unit": "PC",
        "fefta_judgment": "UNKNOWN",
    })
    db_session.commit()
    fetched = repo.get(instance.id, client_id=admin_user.client_id)
    assert fetched is not None
    assert fetched.material_code == "MAT-REPO-1"


def test_base_repo_tenant_isolation(db_session, admin_user):
    repo = BaseRepository(Material, db_session)
    repo.create({
        "client_id": "TENANT_A",
        "material_code": "MAT-X",
        "description": "Tenant A material",
        "material_type": "ROH",
        "base_unit": "PC",
        "fefta_judgment": "UNKNOWN",
    })
    repo.create({
        "client_id": "TENANT_B",
        "material_code": "MAT-X",  # same code, different tenant
        "description": "Tenant B material",
        "material_type": "ROH",
        "base_unit": "PC",
        "fefta_judgment": "UNKNOWN",
    })
    db_session.commit()

    a_results = repo.list(client_id="TENANT_A")
    b_results = repo.list(client_id="TENANT_B")
    assert len(a_results) == 1
    assert len(b_results) == 1
    assert a_results[0].description == "Tenant A material"
    assert b_results[0].description == "Tenant B material"


def test_base_repo_filters(db_session, admin_user):
    repo = BaseRepository(Material, db_session)
    for i, mt in enumerate(["FERT", "FERT", "ROH"]):
        repo.create({
            "client_id": admin_user.client_id,
            "material_code": f"MAT-FILT-{i}",
            "description": f"Item {i}",
            "material_type": mt,
            "base_unit": "PC",
            "fefta_judgment": "UNKNOWN",
        })
    db_session.commit()

    fert_count = repo.count(client_id=admin_user.client_id,
                            filters={"material_type": "FERT"})
    assert fert_count == 2


def test_base_repo_pagination(db_session, admin_user):
    repo = BaseRepository(Material, db_session)
    for i in range(10):
        repo.create({
            "client_id": admin_user.client_id,
            "material_code": f"MAT-P-{i}",
            "description": f"P{i}",
            "material_type": "ROH",
            "base_unit": "PC",
            "fefta_judgment": "UNKNOWN",
        })
    db_session.commit()

    page1 = repo.list(client_id=admin_user.client_id, skip=0, limit=4)
    page2 = repo.list(client_id=admin_user.client_id, skip=4, limit=4)
    assert len(page1) == 4
    assert len(page2) == 4
    # No overlap
    assert {m.id for m in page1}.isdisjoint({m.id for m in page2})
