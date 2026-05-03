"""End-to-end integration test between ERP and AI_TM Stub.

Run BOTH servers first:
    Terminal 1: uvicorn app.main:app --port 5000 --reload
    Terminal 2: uvicorn ai_tm_stub.main:app --port 5001 --reload

Then with `AI_TM_MOCK_MODE=false` in ERP's .env, run this script:
    python scripts/integration_test.py

What this verifies:
  1. ERP -> AI_TM (POST /hs/classify, /gaihi/judge, /export/precheck)
  2. ERP -> AI_TM (POST /gaihi/judge-bom for multi-level BOM)
  3. AI_TM -> ERP (GET /pp/compliance/snapshot)
  4. AI_TM -> ERP (POST /gts/webhook/judgment-updated)
  5. End-to-end workflow via AI_TM's /workflows/reassess-bom endpoint
"""
import sys
from pathlib import Path

import httpx

ERP_BASE = "http://localhost:5000"
AI_TM_BASE = "http://localhost:5001"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin1234"


def banner(title: str):
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def login(base_url: str, email: str, password: str) -> str:
    r = httpx.post(f"{base_url}/auth/token",
                   data={"username": email, "password": password},
                   timeout=10.0)
    r.raise_for_status()
    return r.json()["access_token"]


def check_servers_alive() -> bool:
    """Verify both servers are reachable."""
    try:
        r1 = httpx.get(f"{ERP_BASE}/health", timeout=2.0)
        r2 = httpx.get(f"{AI_TM_BASE}/health", timeout=2.0)
        return r1.status_code == 200 and r2.status_code == 200
    except httpx.HTTPError:
        return False


def test_direct_ai_tm_endpoints():
    banner("Test 1: Direct calls to AI_TM stub (mimics ERP -> AI_TM)")

    # 1a. HS classify
    r = httpx.post(f"{AI_TM_BASE}/hs/classify", json={
        "description": "ArF Immersion Photoresist NSP-AR450",
    })
    print(f"  POST /hs/classify -> {r.status_code}  hs={r.json()['hs_code']}  "
          f"confidence={r.json()['confidence']}")

    # 1b. 該非判定
    r = httpx.post(f"{AI_TM_BASE}/gaihi/judge", json={
        "material_code": "MAT-4000003",
        "description": "Hafnium Precursor for ALD HfCl4",
    })
    j = r.json()
    print(f"  POST /gaihi/judge  -> {r.status_code}  judgment={j['judgment']}  "
          f"eccn={j['eccn']}  license={j['requires_license']}")

    # 1c. Export precheck
    r = httpx.post(f"{AI_TM_BASE}/export/precheck", json={
        "reference": "TEST-SO-001",
        "destination_country": "CN",
        "customer_code": "BP-3000005",
        "customer_name": "Test China Customer",
        "items": [{"material_code": "MAT-4000003", "quantity": 5,
                  "eccn": "3C001", "hs_code": "2931.90"}],
    })
    e = r.json()
    print(f"  POST /export/precheck -> {r.status_code}  decision={e['decision']}  "
          f"message={e['message']}")


def test_erp_to_ai_tm_bom_judge(erp_token: str):
    banner("Test 2: ERP -> AI_TM BOM judgment via ERP's GTS endpoint")
    # ERP exposes /gts/judge-bom which internally calls AI_TM via the
    # configured client (HTTP when AI_TM_MOCK_MODE=false)
    r = httpx.post(
        f"{ERP_BASE}/gts/judge-bom",
        params={"material_code": "MAT-1000001", "plant_code": "1000"},
        headers={"Authorization": f"Bearer {erp_token}"},
        timeout=15.0,
    )
    if r.status_code != 200:
        print(f"  FAILED: status={r.status_code}  body={r.text}")
        return
    body = r.json()
    print(f"  ERP returned: judgment={body['judgment']}  "
          f"eccn={body.get('aggregate_eccn')}  "
          f"foreign_share={body['foreign_origin_share_percent']}%")
    print(f"  controlled components: {body['controlled_components']}")
    print("  risk factors:")
    for rf in body["risk_factors"]:
        print(f"    - {rf}")
    print(f"  rationale: {body['rationale']}")


def test_ai_tm_to_erp_workflow(erp_token: str):
    banner("Test 3: AI_TM-driven workflow (AI_TM pulls ERP data, judges, writes back)")
    # AI_TM endpoint orchestrates GET (snapshot) + judgment + POST (webhook)
    r = httpx.post(f"{AI_TM_BASE}/workflows/reassess-bom", json={
        "erp_base_url": ERP_BASE,
        "erp_token": erp_token,
        "material_code": "MAT-1000001",
        "plant_code": "1000",
    }, timeout=15.0)
    if r.status_code != 200:
        print(f"  FAILED: status={r.status_code}  body={r.text}")
        return
    body = r.json()
    print(f"  snapshot fetched: {body['snapshot_components']} components")
    print(f"  judgment computed: {body['judgment']}")
    print(f"  rationale: {body['rationale']}")
    print(f"  ERP webhook writeback status: {body['erp_writeback_status']}")
    print(f"  duration: {body['started_at']} -> {body['finished_at']}")


def test_verify_writeback_landed(erp_token: str):
    banner("Test 4: Verify ERP material was updated by AI_TM webhook")
    r = httpx.get(f"{ERP_BASE}/mdm/materials",
                  params={"limit": 200},
                  headers={"Authorization": f"Bearer {erp_token}"},
                  timeout=10.0)
    items = r.json()["items"]
    target = next((m for m in items if m["material_code"] == "MAT-1000001"), None)
    if not target:
        print("  MAT-1000001 not found")
        return
    print(f"  MAT-1000001 fefta_judgment = {target['fefta_judgment']}")
    print(f"  MAT-1000001 eccn          = {target['eccn']}")


def main():
    print("Integration test for ERP <-> AI_TM_Stub")
    print(f"  ERP:    {ERP_BASE}")
    print(f"  AI_TM:  {AI_TM_BASE}")

    if not check_servers_alive():
        print("\n❌ Server(s) not reachable. Please start both:")
        print("   uvicorn app.main:app --port 5000 --reload")
        print("   uvicorn ai_tm_stub.main:app --port 5001 --reload")
        sys.exit(1)
    print("  ✓ Both servers responding")

    erp_token = login(ERP_BASE, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  ✓ Logged into ERP (token len={len(erp_token)})")

    test_direct_ai_tm_endpoints()
    test_erp_to_ai_tm_bom_judge(erp_token)
    test_ai_tm_to_erp_workflow(erp_token)
    test_verify_writeback_landed(erp_token)

    print("\n" + "=" * 70)
    print("  ✓ Integration test complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
