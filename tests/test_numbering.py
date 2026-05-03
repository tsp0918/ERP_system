"""Tests for the document numbering service."""
from app.core.numbering import next_number


def test_material_numbering(db_session):
    n1 = next_number(db_session, "DEMO", "MATERIAL")
    n2 = next_number(db_session, "DEMO", "MATERIAL")
    assert n1 == "MAT-0000001"
    assert n2 == "MAT-0000002"


def test_sales_order_numbering(db_session):
    n1 = next_number(db_session, "DEMO", "SALES_ORDER")
    n2 = next_number(db_session, "DEMO", "SALES_ORDER")
    # SAP-style 10-digit, starting at 10_000_000
    assert int(n1) == 10_000_000
    assert int(n2) == 10_000_001
    assert len(n1) == 10  # zero-padded


def test_independent_ranges(db_session):
    """Different range codes have independent counters."""
    m = next_number(db_session, "DEMO", "MATERIAL")
    bp = next_number(db_session, "DEMO", "BUSINESS_PARTNER")
    assert m == "MAT-0000001"
    assert bp == "BP-0000001"


def test_tenant_isolation(db_session):
    """Different clients get separate counters."""
    a = next_number(db_session, "TENANT_A", "MATERIAL")
    b = next_number(db_session, "TENANT_B", "MATERIAL")
    assert a == "MAT-0000001"
    assert b == "MAT-0000001"  # both start at 1, separately
