"""Tests for AI_TM integration via the mock client."""
from app.integrations.ai_trade_management.client import _MockClient
from app.integrations.ai_trade_management import schemas as ai_schemas


def test_mock_hs_classify_match():
    c = _MockClient()
    r = c.hs_classify(ai_schemas.HSClassifyRequest(
        description="ArF Photoresist NSP-XX",
    ))
    assert r.hs_code == "3707.90"
    assert r.confidence > 0.8


def test_mock_hs_classify_default():
    c = _MockClient()
    r = c.hs_classify(ai_schemas.HSClassifyRequest(
        description="Random unknown product",
    ))
    assert r.hs_code == "3824.99"
    assert r.confidence < 0.5


def test_mock_gaihi_judge_controlled():
    c = _MockClient()
    r = c.gaihi_judge(ai_schemas.GaihiJudgeRequest(
        material_code="X", description="Process Gas Silane",
    ))
    assert r.judgment == "APPLICABLE"
    assert r.eccn == "3C001"
    assert r.requires_license is True


def test_mock_gaihi_judge_not_applicable():
    c = _MockClient()
    r = c.gaihi_judge(ai_schemas.GaihiJudgeRequest(
        material_code="X", description="Generic chemical mixture",
    ))
    assert r.judgment == "NOT_APPLICABLE"
    assert r.eccn == "EAR99"


def test_mock_export_check_blocked_country():
    c = _MockClient()
    r = c.export_check(ai_schemas.ExportCheckRequest(
        reference="SO-1", destination_country="IR",
        customer_code="X", customer_name="Test",
        items=[],
    ))
    assert r.decision == "BLOCKED"


def test_mock_export_check_needs_license():
    c = _MockClient()
    r = c.export_check(ai_schemas.ExportCheckRequest(
        reference="SO-2", destination_country="JP",
        customer_code="X", customer_name="Test",
        items=[ai_schemas.ExportCheckItem(
            material_code="MAT-X", quantity=1.0,
            eccn="3C001", hs_code="X",
        )],
    ))
    assert r.decision == "NEEDS_LICENSE"


def test_mock_judge_bom_aggregates_correctly():
    c = _MockClient()
    r = c.judge_bom(ai_schemas.BomJudgeRequest(
        material_code="MAT-FIN", plant_code="P1",
        components=[
            ai_schemas.BomComponent(
                level=1, material_code="C1",
                description="Normal raw material",
                quantity=10, unit="KG",
                country_of_origin="JP",
                eccn="EAR99",
            ),
            ai_schemas.BomComponent(
                level=1, material_code="C2",
                description="Process Gas (controlled)",
                quantity=2, unit="KG",
                country_of_origin="JP",
                eccn="3C001",
            ),
        ],
    ))
    assert r.judgment == "APPLICABLE"
    assert "C2" in r.controlled_components


def test_mock_judge_bom_foreign_origin_review():
    """If 30% of input quantity is from CN, judgment becomes NEEDS_REVIEW."""
    c = _MockClient()
    r = c.judge_bom(ai_schemas.BomJudgeRequest(
        material_code="MAT-FIN", plant_code="P1",
        components=[
            ai_schemas.BomComponent(
                level=1, material_code="C1",
                description="JP material", quantity=70,
                unit="KG", country_of_origin="JP", eccn="EAR99",
            ),
            ai_schemas.BomComponent(
                level=1, material_code="C2",
                description="CN material", quantity=30,
                unit="KG", country_of_origin="CN", eccn="EAR99",
            ),
        ],
    ))
    assert r.judgment == "NEEDS_REVIEW"
    assert r.foreign_origin_share_percent >= 25.0
