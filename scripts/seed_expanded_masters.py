"""取引先・品目マスターデータ拡充シード。

取引先: 顧客 (KR/TW/CN/EU/SEA/高リスク) / 仕入先 / 代理店 / 船会社・フォワーダー
品目: ROH(原材料) / HALB(中間体・自社製造部品) / FERT(完成品・装置) / HAWA(購入部品)

  source .venv/bin/activate
  python scripts/seed_expanded_masters.py
"""
import os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AI_TM_MOCK_MODE"] = "true"

from decimal import Decimal
from sqlalchemy.orm import Session

from app.core.database import engine, create_all_tables
from app.modules.mdm.models import BusinessPartner, Material, MaterialPlant
from app.modules.gts.service import GTSService

CLIENT_ID = "DEMO"
USER = "admin@example.com"

# ══════════════════════════════════════════════════════════════════════
# 1. BUSINESS PARTNERS
# ══════════════════════════════════════════════════════════════════════
NEW_BUSINESS_PARTNERS = [

    # ── 顧客 (Customers) - Korea ───────────────────────────────────
    {"bp_code":"BP-SAMADV-KR","name":"Samsung Advanced Chemicals Co., Ltd.","country":"KR",
     "roles":"CUSTOMER","city":"Suwon","email":"chem-procurement@samsung.com",
     "currency":"KRW","credit_limit":2000000000,"payment_terms":"NET30"},
    {"bp_code":"BP-SKSPEC-KR","name":"SK Specialty Co., Ltd.","country":"KR",
     "roles":"CUSTOMER","city":"Seoul","email":"purchase@skspecialty.com",
     "currency":"KRW","credit_limit":1500000000,"payment_terms":"NET30"},
    {"bp_code":"BP-DBHITEK-KR","name":"DB HiTek Co., Ltd.","country":"KR",
     "roles":"CUSTOMER","city":"Bucheon","email":"material@dbhitek.co.kr",
     "currency":"KRW","credit_limit":800000000,"payment_terms":"NET60"},
    {"bp_code":"BP-DONGWON-KR","name":"Dongwon Chemical & Materials Co.","country":"KR",
     "roles":"CUSTOMER","city":"Daejeon","email":"procurement@dongwon.co.kr",
     "currency":"KRW","credit_limit":500000000,"payment_terms":"NET45"},

    # ── 顧客 (Customers) - Taiwan ──────────────────────────────────
    {"bp_code":"BP-TSMC-PUR-TW","name":"TSMC Purchasing Department","country":"TW",
     "roles":"CUSTOMER","city":"Hsinchu","email":"purchasing@tsmc.com",
     "currency":"USD","credit_limit":5000000000,"payment_terms":"NET30"},
    {"bp_code":"BP-PWRCHIP-TW","name":"Powerchip Semiconductor Manufacturing Corp.","country":"TW",
     "roles":"CUSTOMER","city":"Hsinchu","email":"materials@powerchip.com.tw",
     "currency":"USD","credit_limit":600000000,"payment_terms":"NET45"},
    {"bp_code":"BP-GWAFER-TW","name":"Global Wafers Co., Ltd.","country":"TW",
     "roles":"CUSTOMER","city":"Zhubei","email":"chem@globalwafers.com",
     "currency":"USD","credit_limit":900000000,"payment_terms":"NET30"},
    {"bp_code":"BP-MEDIATEK-TW","name":"MediaTek Inc. (Process Materials)","country":"TW",
     "roles":"CUSTOMER","city":"Hsinchu","email":"supply@mediatek.com",
     "currency":"USD","credit_limit":400000000,"payment_terms":"NET45"},
    {"bp_code":"BP-UMC-TW","name":"United Microelectronics Corporation","country":"TW",
     "roles":"CUSTOMER","city":"Hsinchu","email":"procurement@umc.com",
     "currency":"USD","credit_limit":1200000000,"payment_terms":"NET30"},

    # ── 顧客 (Customers) - China ───────────────────────────────────
    # Note: YMTC はBIS Entity List懸念 → screening で検知
    {"bp_code":"BP-YMTC-CN","name":"Yangtze Memory Technologies Co., Ltd.","country":"CN",
     "roles":"CUSTOMER","city":"Wuhan","email":"supply@ymtc.com",
     "currency":"USD","credit_limit":300000000,"payment_terms":"NET60"},
    {"bp_code":"BP-HUAHONG-CN","name":"Hua Hong Semiconductor Ltd.","country":"CN",
     "roles":"CUSTOMER","city":"Shanghai","email":"procurement@huahong.com",
     "currency":"USD","credit_limit":250000000,"payment_terms":"NET60"},
    {"bp_code":"BP-NEXCHIP-CN","name":"Nexchip Semiconductor Corporation","country":"CN",
     "roles":"CUSTOMER","city":"Hefei","email":"purchase@nexchip.com",
     "currency":"USD","credit_limit":200000000,"payment_terms":"NET60"},

    # ── 顧客 (Customers) - Europe ──────────────────────────────────
    {"bp_code":"BP-INFINEON-DE","name":"Infineon Technologies AG","country":"DE",
     "roles":"CUSTOMER","city":"Munich","email":"chemicals@infineon.com",
     "currency":"EUR","credit_limit":1000000000,"payment_terms":"NET30"},
    {"bp_code":"BP-NXP-NL","name":"NXP Semiconductors Netherlands B.V.","country":"NL",
     "roles":"CUSTOMER","city":"Eindhoven","email":"procurement@nxp.com",
     "currency":"EUR","credit_limit":800000000,"payment_terms":"NET30"},
    {"bp_code":"BP-STMICRO-FR","name":"STMicroelectronics S.A.","country":"FR",
     "roles":"CUSTOMER","city":"Crolles","email":"supply.chain@st.com",
     "currency":"EUR","credit_limit":900000000,"payment_terms":"NET45"},
    {"bp_code":"BP-IMEC-BE","name":"IMEC vzw","country":"BE",
     "roles":"CUSTOMER","city":"Leuven","email":"purchasing@imec.be",
     "currency":"EUR","credit_limit":100000000,"payment_terms":"NET30"},
    {"bp_code":"BP-BOSCH-DE","name":"Robert Bosch Semiconductor GmbH","country":"DE",
     "roles":"CUSTOMER","city":"Reutlingen","email":"materials@bosch.com",
     "currency":"EUR","credit_limit":600000000,"payment_terms":"NET30"},

    # ── 顧客 (Customers) - Southeast Asia ─────────────────────────
    {"bp_code":"BP-UTAC-SG","name":"UTAC Holdings Ltd.","country":"SG",
     "roles":"CUSTOMER","city":"Singapore","email":"materials@utac.com",
     "currency":"USD","credit_limit":150000000,"payment_terms":"NET45"},
    {"bp_code":"BP-ISSI-TH","name":"Integrated Silicon Solution (Thailand)","country":"TH",
     "roles":"CUSTOMER","city":"Ayutthaya","email":"procurement@issi-th.com",
     "currency":"USD","credit_limit":80000000,"payment_terms":"NET45"},
    {"bp_code":"BP-PENANG-MY","name":"Penang Silicon Sdn. Bhd.","country":"MY",
     "roles":"CUSTOMER","city":"Penang","email":"supply@penangsilicon.com",
     "currency":"USD","credit_limit":100000000,"payment_terms":"NET60"},
    {"bp_code":"BP-NEXPERIA-PH","name":"Nexperia Philippines Inc.","country":"PH",
     "roles":"CUSTOMER","city":"Cabuyao","email":"procurement@nexperia.com",
     "currency":"USD","credit_limit":120000000,"payment_terms":"NET45"},
    {"bp_code":"BP-VIET-SEMI-VN","name":"Vietnam Semiconductor Materials JSC","country":"VN",
     "roles":"CUSTOMER","city":"Ha Noi","email":"import@vietsemi.vn",
     "currency":"USD","credit_limit":50000000,"payment_terms":"NET60"},

    # ── 顧客 (Customers) - Japan domestic ─────────────────────────
    {"bp_code":"BP-KIOXIA-JP","name":"Kioxia Corporation","country":"JP",
     "roles":"CUSTOMER","city":"Tokyo","email":"procurement@kioxia.com",
     "currency":"JPY","credit_limit":3000000000,"payment_terms":"NET30"},
    {"bp_code":"BP-RENESAS-JP","name":"Renesas Electronics Corporation","country":"JP",
     "roles":"CUSTOMER","city":"Tokyo","email":"materials@renesas.com",
     "currency":"JPY","credit_limit":2000000000,"payment_terms":"NET30"},
    {"bp_code":"BP-TOSHIBA-JP","name":"Toshiba Device & Storage Corporation","country":"JP",
     "roles":"CUSTOMER","city":"Yokohama","email":"supply@toshiba-ds.com",
     "currency":"JPY","credit_limit":1500000000,"payment_terms":"NET30"},

    # ── 顧客 (HIGH-RISK - 要注意) ──────────────────────────────────
    # UAE based - possible Iran re-export channel
    {"bp_code":"BP-GALAXYHZN-AE","name":"Galaxy Horizon Trading LLC","country":"AE",
     "roles":"CUSTOMER","city":"Dubai","email":"trade@galaxyhorizon.ae",
     "currency":"USD","credit_limit":50000000,"payment_terms":"NET30"},
    # India - dual-use end-user concern
    {"bp_code":"BP-INDOTECH-IN","name":"Indo Advanced Semiconductor Materials Pvt. Ltd.","country":"IN",
     "roles":"CUSTOMER","city":"Bengaluru","email":"import@indoadvanced.in",
     "currency":"USD","credit_limit":80000000,"payment_terms":"NET45"},
    # Turkey - transit / re-export risk
    {"bp_code":"BP-ANATOLTECH-TR","name":"Anadolu Technology Distribution A.Ş.","country":"TR",
     "roles":"CUSTOMER","city":"Istanbul","email":"import@anatoltech.com.tr",
     "currency":"USD","credit_limit":30000000,"payment_terms":"NET60"},
    # Russia - CAATSA / elevated risk (should hit possible_match on screening)
    {"bp_code":"BP-ANGSTREM-RU","name":"Angstrem-T OJSC","country":"RU",
     "roles":"CUSTOMER","city":"Zelenograd","email":"supply@angstrem.ru",
     "currency":"USD","credit_limit":20000000,"payment_terms":"NET60"},
    # North Korea front company → should be BLOCKED
    {"bp_code":"BP-PYONGTEK-KP","name":"Pyongyang Technology Import Corporation","country":"KP",
     "roles":"CUSTOMER","city":"Pyongyang","email":"tech@ptimport.kp",
     "currency":"USD","credit_limit":0,"payment_terms":"NET60"},

    # ── 仕入先 (Vendors) - Chemical ────────────────────────────────
    {"bp_code":"VND-DOW-US","name":"Dow Chemical Company","country":"US",
     "roles":"VENDOR","city":"Midland, MI","email":"supply@dow.com","currency":"USD"},
    {"bp_code":"VND-BASF-DE","name":"BASF SE Electronic Materials","country":"DE",
     "roles":"VENDOR","city":"Ludwigshafen","email":"electronic.materials@basf.com","currency":"EUR"},
    {"bp_code":"VND-SHINETSU-JP","name":"Shin-Etsu Chemical Co., Ltd.","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"sales@shinetsu.co.jp","currency":"JPY"},
    {"bp_code":"VND-WAKO-JP","name":"Fujifilm Wako Pure Chemical Corporation","country":"JP",
     "roles":"VENDOR","city":"Osaka","email":"sales@wako-chem.co.jp","currency":"JPY"},
    {"bp_code":"VND-KANTO-JP","name":"Kanto Chemical Co., Inc.","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"sales@kanto.co.jp","currency":"JPY"},
    {"bp_code":"VND-MERCK-DE","name":"Merck KGaA Electronic Materials","country":"DE",
     "roles":"VENDOR","city":"Darmstadt","email":"em-sales@merck.de","currency":"EUR"},
    {"bp_code":"VND-AIRPROD-US","name":"Air Products and Chemicals, Inc.","country":"US",
     "roles":"VENDOR","city":"Allentown, PA","email":"semiconductor@airproducts.com","currency":"USD"},
    {"bp_code":"VND-LINDE-DE","name":"Linde GmbH Semiconductor Gases","country":"DE",
     "roles":"VENDOR","city":"Munich","email":"semiconductor.gases@linde.com","currency":"EUR"},
    {"bp_code":"VND-STELLA-JP","name":"Stella Chemifa Corporation","country":"JP",
     "roles":"VENDOR","city":"Osaka","email":"sales@stellachemifa.co.jp","currency":"JPY"},
    {"bp_code":"VND-SOLVAY-BE","name":"Solvay S.A. Specialty Polymers","country":"BE",
     "roles":"VENDOR","city":"Brussels","email":"sp-sales@solvay.com","currency":"EUR"},
    {"bp_code":"VND-ENTEGRIS-US","name":"Entegris, Inc.","country":"US",
     "roles":"VENDOR","city":"Billerica, MA","email":"sales@entegris.com","currency":"USD"},
    {"bp_code":"VND-OLIN-US","name":"Olin Corporation Chlor Alkali","country":"US",
     "roles":"VENDOR","city":"Clayton, MO","email":"sales@olin.com","currency":"USD"},
    # Russian chemical supplier - elevated risk (CAATSA concern)
    {"bp_code":"VND-KHIMTEK-RU","name":"Khimtek Specialty Chemicals JSC","country":"RU",
     "roles":"VENDOR","city":"Saint Petersburg","email":"export@khimtek.ru","currency":"RUB"},

    # ── 仕入先 (Vendors) - Equipment Parts ────────────────────────
    {"bp_code":"VND-KLA-US","name":"KLA Corporation","country":"US",
     "roles":"VENDOR","city":"Milpitas, CA","email":"parts@kla.com","currency":"USD"},
    {"bp_code":"VND-PALL-US","name":"Pall Corporation (Danaher)","country":"US",
     "roles":"VENDOR","city":"Port Washington, NY","email":"filter-sales@pall.com","currency":"USD"},
    {"bp_code":"VND-VALQUA-JP","name":"Nippon Valqua Industries, Ltd.","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"sales@valqua.co.jp","currency":"JPY"},
    {"bp_code":"VND-PILKINGTON-UK","name":"Pilkington Micro Electronics Ltd.","country":"GB",
     "roles":"VENDOR","city":"St Helens","email":"me-sales@pilkington.com","currency":"GBP"},

    # ── 代理店 / 商社 (Agents / Trading) ──────────────────────────
    {"bp_code":"AGT-MARUBENI-JP","name":"Marubeni Corporation (Chemical Division)","country":"JP",
     "roles":"CUSTOMER,VENDOR","city":"Tokyo","email":"chem@marubeni.com","currency":"JPY"},
    {"bp_code":"AGT-ITOCHU-JP","name":"Itochu Chemicals America Inc. (JP)","country":"JP",
     "roles":"CUSTOMER,VENDOR","city":"Tokyo","email":"chemicals@itochu.co.jp","currency":"JPY"},
    {"bp_code":"AGT-MITSUBISHI-JP","name":"Mitsubishi Chemical Trading Corporation","country":"JP",
     "roles":"CUSTOMER,VENDOR","city":"Tokyo","email":"trading@mitsubishi-chem.co.jp","currency":"JPY"},
    {"bp_code":"AGT-BRENNTAG-DE","name":"Brenntag SE","country":"DE",
     "roles":"VENDOR","city":"Essen","email":"semiconductor@brenntag.com","currency":"EUR"},
    {"bp_code":"AGT-UNIVAR-US","name":"Univar Solutions Inc.","country":"US",
     "roles":"VENDOR","city":"Downers Grove, IL","email":"electronics@univarsolutions.com","currency":"USD"},
    {"bp_code":"AGT-CHIMIEPLUS-FR","name":"Chimie Plus Laboratoires","country":"FR",
     "roles":"CUSTOMER,VENDOR","city":"Paris","email":"import@chimieplus.fr","currency":"EUR"},

    # ── 船会社 / フォワーダー (Shipping / Forwarder) ───────────────
    {"bp_code":"SHP-MAERSK-DK","name":"A.P. Moller - Maersk A/S","country":"DK",
     "roles":"VENDOR","city":"Copenhagen","email":"dangerous.goods@maersk.com","currency":"USD"},
    {"bp_code":"SHP-MSC-CH","name":"Mediterranean Shipping Company S.A.","country":"CH",
     "roles":"VENDOR","city":"Geneva","email":"chemicals@msc.com","currency":"USD"},
    {"bp_code":"SHP-CMACGM-FR","name":"CMA CGM S.A.","country":"FR",
     "roles":"VENDOR","city":"Marseille","email":"hazmat@cma-cgm.com","currency":"USD"},
    # COSCO - possible match (一部子会社がSDNリスト掲載)
    {"bp_code":"SHP-COSCO-CN","name":"COSCO SHIPPING Holdings Co., Ltd.","country":"CN",
     "roles":"VENDOR","city":"Shanghai","email":"booking@cosco.com","currency":"USD"},
    {"bp_code":"SHP-EVERGREEN-TW","name":"Evergreen Marine Corporation","country":"TW",
     "roles":"VENDOR","city":"Taipei","email":"dangerous@evergreen-marine.com","currency":"USD"},
    {"bp_code":"FWD-NIPPONEX-JP","name":"Nippon Express Co., Ltd. (International)","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"intl.chem@nittsu.co.jp","currency":"JPY"},
    {"bp_code":"FWD-YUSEN-JP","name":"Yusen Logistics Co., Ltd.","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"chemical.logistics@yusen.co.jp","currency":"JPY"},
    {"bp_code":"FWD-KINTETSU-JP","name":"Kintetsu World Express, Inc.","country":"JP",
     "roles":"VENDOR","city":"Tokyo","email":"dangerous.goods@kwe.co.jp","currency":"JPY"},
    {"bp_code":"FWD-DHL-DE","name":"DHL Global Forwarding GmbH","country":"DE",
     "roles":"VENDOR","city":"Bonn","email":"chemical.compliance@dhl.com","currency":"EUR"},
    {"bp_code":"FWD-CEVA-NL","name":"CEVA Logistics Netherlands B.V.","country":"NL",
     "roles":"VENDOR","city":"Amsterdam","email":"hazmat@cevalogistics.com","currency":"EUR"},
    # Sovcomflot - OFAC SDN (Russian shipping company) → should be BLOCKED
    {"bp_code":"SHP-SOVCOMFLOT-RU","name":"Public Joint-Stock Company Sovcomflot","country":"RU",
     "roles":"VENDOR","city":"Saint Petersburg","email":"chartering@sovcomflot.ru","currency":"RUB"},
]

# ══════════════════════════════════════════════════════════════════════
# 2. MATERIALS
# ══════════════════════════════════════════════════════════════════════
NEW_MATERIALS = [

    # ── ROH: 原材料 ────────────────────────────────────────────────
    {"material_code":"MAT-R0001","description":"IPA Electronic Grade 99.9% (Isopropyl Alcohol)",
     "material_type":"ROH","base_unit":"L","hs_code":"2905.12","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("180"),"currency":"JPY"},
    {"material_code":"MAT-R0002","description":"NMP N-Methyl-2-pyrrolidone Semiconductor Grade",
     "material_type":"ROH","base_unit":"KG","hs_code":"2933.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("850"),"currency":"JPY"},
    {"material_code":"MAT-R0003","description":"Hydrogen Fluoride HF 49% Electronic Grade",
     "material_type":"ROH","base_unit":"KG","hs_code":"2811.11","eccn":"1C350",
     "country_of_origin":"JP","standard_price":Decimal("2200"),"currency":"JPY"},
    {"material_code":"MAT-R0004","description":"Sulfuric Acid H2SO4 98% Ultra-Pure",
     "material_type":"ROH","base_unit":"KG","hs_code":"2807.00","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("120"),"currency":"JPY"},
    {"material_code":"MAT-R0005","description":"Trimethylaluminum TMAl ALD Precursor (US origin)",
     "material_type":"ROH","base_unit":"KG","hs_code":"2931.90","eccn":"1C351",
     "country_of_origin":"US","standard_price":Decimal("180000"),"currency":"JPY"},
    {"material_code":"MAT-R0006","description":"Ammonia NH3 Semiconductor Grade 6N",
     "material_type":"ROH","base_unit":"KG","hs_code":"2814.10","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("600"),"currency":"JPY"},
    {"material_code":"MAT-R0007","description":"Titanium Tetrachloride TiCl4 Semiconductor Grade",
     "material_type":"ROH","base_unit":"KG","hs_code":"2827.39","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("15000"),"currency":"JPY"},
    {"material_code":"MAT-R0008","description":"TEOS Tetraethyl Orthosilicate CVD Grade (DE origin)",
     "material_type":"ROH","base_unit":"KG","hs_code":"2931.90","eccn":"EAR99",
     "country_of_origin":"DE","standard_price":Decimal("8500"),"currency":"JPY"},
    {"material_code":"MAT-R0009","description":"Diborane B2H6 Dopant Gas 1% in H2",
     "material_type":"ROH","base_unit":"KG","hs_code":"2850.00","eccn":"1C350",
     "country_of_origin":"US","standard_price":Decimal("95000"),"currency":"JPY"},
    {"material_code":"MAT-R0010","description":"Phosphine PH3 Dopant Gas 1% in H2",
     "material_type":"ROH","base_unit":"KG","hs_code":"2853.90","eccn":"1C350",
     "country_of_origin":"JP","standard_price":Decimal("85000"),"currency":"JPY"},
    {"material_code":"MAT-R0011","description":"Specialty Solvent SPE-RU01 (Russian origin, Khimtek)",
     "material_type":"ROH","base_unit":"KG","hs_code":"2901.10","eccn":"EAR99",
     "country_of_origin":"RU","standard_price":Decimal("1200"),"currency":"JPY"},

    # ── HALB: 製造中間体 ───────────────────────────────────────────
    {"material_code":"MAT-I0001","description":"ArF Photoresist Base Polymer (US origin, Dow)",
     "material_type":"HALB","base_unit":"KG","hs_code":"3907.99","eccn":"3E001",
     "country_of_origin":"US","standard_price":Decimal("450000"),"currency":"JPY"},
    {"material_code":"MAT-I0002","description":"EUV CAR Resist Base Polymer (US/JP origin)",
     "material_type":"HALB","base_unit":"KG","hs_code":"3907.99","eccn":"3B001",
     "country_of_origin":"US","standard_price":Decimal("1200000"),"currency":"JPY"},
    {"material_code":"MAT-I0003","description":"BARC Anti-Reflective Coating Base Formulation",
     "material_type":"HALB","base_unit":"KG","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("95000"),"currency":"JPY"},
    {"material_code":"MAT-I0004","description":"CMP Slurry Concentrate Base (Al2O3 abrasive)",
     "material_type":"HALB","base_unit":"KG","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("8500"),"currency":"JPY"},
    {"material_code":"MAT-I0005","description":"Developer TMAH 2.38% Electronic Grade",
     "material_type":"HALB","base_unit":"L","hs_code":"2923.90","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("950"),"currency":"JPY"},
    {"material_code":"MAT-I0006","description":"Chemical Pump Assembly (DE origin, Linde subsystem)",
     "material_type":"HALB","base_unit":"PC","hs_code":"8413.81","eccn":"EAR99",
     "country_of_origin":"DE","standard_price":Decimal("1800000"),"currency":"JPY"},
    {"material_code":"MAT-I0007","description":"Chemical Process Control PCB Assembly (JP origin)",
     "material_type":"HALB","base_unit":"PC","hs_code":"8537.10","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("350000"),"currency":"JPY"},
    {"material_code":"MAT-I0008","description":"Fluoropolymer PFA Tubing Assembly 1/4inch",
     "material_type":"HALB","base_unit":"M","hs_code":"3917.29","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("12000"),"currency":"JPY"},

    # ── FERT: 完成品 (追加品) ──────────────────────────────────────
    {"material_code":"MAT-F0001","description":"EUV Photoresist EUV-RS100 13.5nm (High-End)",
     "material_type":"FERT","base_unit":"L","hs_code":"3707.90","eccn":"3B001",
     "country_of_origin":"JP","standard_price":Decimal("2800000"),"currency":"JPY"},
    {"material_code":"MAT-F0002","description":"CMP Slurry for STI Premium NSC-STI45",
     "material_type":"FERT","base_unit":"KG","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("8200"),"currency":"JPY"},
    {"material_code":"MAT-F0003","description":"Spin-on-Carbon Hard Mask SOC-200 (193nm patterning)",
     "material_type":"FERT","base_unit":"L","hs_code":"3707.90","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("180000"),"currency":"JPY"},
    {"material_code":"MAT-F0004","description":"TEOS PECVD Precursor Solution (high-purity blend)",
     "material_type":"FERT","base_unit":"KG","hs_code":"2931.90","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("45000"),"currency":"JPY"},
    {"material_code":"MAT-F0005","description":"Buffered HF Etch Solution 50:1 BOE-50",
     "material_type":"FERT","base_unit":"L","hs_code":"2811.19","eccn":"1C350",
     "country_of_origin":"JP","standard_price":Decimal("18000"),"currency":"JPY"},
    {"material_code":"MAT-F0006","description":"W-CMP Slurry Advanced H2O2-free NSC-WSL55",
     "material_type":"FERT","base_unit":"KG","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("14500"),"currency":"JPY"},
    {"material_code":"MAT-F0007","description":"Spin-on-Glass SOG Dielectric NSC-SOG30",
     "material_type":"FERT","base_unit":"L","hs_code":"3707.90","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("95000"),"currency":"JPY"},
    {"material_code":"MAT-F0008","description":"Photoresist Stripping Solution NMP-Free NSC-STR02",
     "material_type":"FERT","base_unit":"L","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("12000"),"currency":"JPY"},
    {"material_code":"MAT-F0009","description":"Cleaning Chemical Kit SC-2 Formulation",
     "material_type":"FERT","base_unit":"L","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("9500"),"currency":"JPY"},
    {"material_code":"MAT-F0010","description":"Copper Interconnect CMP Slurry NSC-CuP22",
     "material_type":"FERT","base_unit":"KG","hs_code":"3824.99","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("16000"),"currency":"JPY"},

    # ── FERT: 装置 / ユニット品 ────────────────────────────────────
    {"material_code":"MAT-E0001","description":"Chemical Delivery System CDS-500 (Point-of-Use)",
     "material_type":"FERT","base_unit":"PC","hs_code":"8419.89","eccn":"3B001",
     "country_of_origin":"JP","standard_price":Decimal("45000000"),"currency":"JPY"},
    {"material_code":"MAT-E0002","description":"Chemical Blending Unit CBU-200 (PFA wetted)",
     "material_type":"FERT","base_unit":"PC","hs_code":"8419.89","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("12000000"),"currency":"JPY"},
    {"material_code":"MAT-E0003","description":"CMP Tool NSC-CMP-Pro100 (300mm wafer process)",
     "material_type":"FERT","base_unit":"PC","hs_code":"8486.20","eccn":"3B001",
     "country_of_origin":"JP","standard_price":Decimal("850000000"),"currency":"JPY"},
    {"material_code":"MAT-E0004","description":"Wafer Surface Cleaning System WCS-200 (SC-1/SC-2)",
     "material_type":"FERT","base_unit":"PC","hs_code":"8486.20","eccn":"3B001",
     "country_of_origin":"JP","standard_price":Decimal("350000000"),"currency":"JPY"},

    # ── HAWA: 購入部品 ─────────────────────────────────────────────
    {"material_code":"MAT-P0001","description":"Fluoropolymer O-Ring Set (FKM/FFKM, cleanroom)",
     "material_type":"HAWA","base_unit":"SET","hs_code":"4016.93","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("45000"),"currency":"JPY"},
    {"material_code":"MAT-P0002","description":"High-Purity Filter Cartridge 0.05μm PTFE",
     "material_type":"HAWA","base_unit":"PC","hs_code":"8421.29","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("85000"),"currency":"JPY"},
    {"material_code":"MAT-P0003","description":"Mass Flow Controller MFC for Chemical Gas",
     "material_type":"HAWA","base_unit":"PC","hs_code":"9026.20","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("280000"),"currency":"JPY"},
    {"material_code":"MAT-P0004","description":"PTFE / PFA Fittings Set (1/4, 3/8, 1/2 inch)",
     "material_type":"HAWA","base_unit":"SET","hs_code":"3917.33","eccn":"EAR99",
     "country_of_origin":"US","standard_price":Decimal("18000"),"currency":"JPY"},
    {"material_code":"MAT-P0005","description":"Chemical Drum Liner HDPE 200L Cleanroom Grade",
     "material_type":"HAWA","base_unit":"PC","hs_code":"3923.10","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("3500"),"currency":"JPY"},

    # ── HALB(E): 自社製造部品 ──────────────────────────────────────
    {"material_code":"MAT-M0001","description":"CMP Polishing Pad Conditioner Disc (Diamond)",
     "material_type":"HALB","base_unit":"PC","hs_code":"6804.23","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("450000"),"currency":"JPY"},
    {"material_code":"MAT-M0002","description":"Chemical Distribution Manifold PFA Welded",
     "material_type":"HALB","base_unit":"PC","hs_code":"3917.39","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("320000"),"currency":"JPY"},
    {"material_code":"MAT-M0003","description":"Automated Chemical Dosing Module (PLC-controlled)",
     "material_type":"HALB","base_unit":"PC","hs_code":"8537.10","eccn":"EAR99",
     "country_of_origin":"JP","standard_price":Decimal("1200000"),"currency":"JPY"},
]


def run():
    create_all_tables()
    with Session(engine) as db:
        gts = GTSService(db)
        bp_created = bp_skipped = bp_blocked = 0
        mat_created = mat_skipped = 0

        print(f"\n{'='*65}")
        print("  [1/2] Business Partner 登録 + Denied-Party スクリーニング")
        print(f"{'='*65}")

        for rec in NEW_BUSINESS_PARTNERS:
            code = rec["bp_code"]
            existing = db.query(BusinessPartner).filter(
                BusinessPartner.client_id == CLIENT_ID,
                BusinessPartner.bp_code == code,
            ).first()
            if existing:
                bp_skipped += 1
                continue

            bp = BusinessPartner(
                client_id=CLIENT_ID,
                bp_code=code,
                bp_type=rec.get("bp_type","ORG"),
                name=rec["name"],
                country=rec["country"],
                roles=rec.get("roles","CUSTOMER"),
                email=rec.get("email"),
                city=rec.get("city"),
                currency=rec.get("currency","USD"),
                credit_limit=Decimal(str(rec["credit_limit"])) if rec.get("credit_limit") else None,
                payment_terms=rec.get("payment_terms"),
                address_line1=rec.get("address_line1"),
                screening_status="UNSCREENED",
                created_by=USER,
                updated_by=USER,
            )
            db.add(bp)
            db.flush()

            gts.screen_business_partner(bp, screened_by=USER)
            db.flush()

            icon = "🚫" if bp.screening_status in ("BLOCKED","FLAGGED") else "✅"
            tag  = " [50%ルール]" if bp.fifty_pct_rule_triggered else ""
            print(f"  {icon} {code:28} {bp.country}  {bp.screening_status:8}{tag}  {bp.denial_list or ''}")
            if bp.screening_status in ("BLOCKED","FLAGGED"):
                bp_blocked += 1
            bp_created += 1

        db.commit()
        print(f"\n  BP: 新規 {bp_created}件 (うち BLOCKED/FLAGGED {bp_blocked}件), スキップ {bp_skipped}件")

        # ── Materials ─────────────────────────────────────────────
        print(f"\n{'='*65}")
        print("  [2/2] 品目マスター登録")
        print(f"{'='*65}")

        for rec in NEW_MATERIALS:
            code = rec["material_code"]
            existing = db.query(Material).filter(
                Material.client_id == CLIENT_ID,
                Material.material_code == code,
            ).first()
            if existing:
                mat_skipped += 1
                continue

            mat = Material(
                client_id=CLIENT_ID,
                material_code=code,
                description=rec["description"],
                material_type=rec["material_type"],
                base_unit=rec.get("base_unit","KG"),
                hs_code=rec.get("hs_code"),
                eccn=rec.get("eccn"),
                country_of_origin=rec.get("country_of_origin"),
                standard_price=rec.get("standard_price"),
                currency=rec.get("currency","JPY"),
                fefta_judgment="UNKNOWN",
                created_by=USER,
                updated_by=USER,
            )
            db.add(mat)
            db.flush()

            # MaterialPlant record
            mp = MaterialPlant(
                client_id=CLIENT_ID,
                material_code=code,
                plant_code="1000",
                procurement_type="E" if rec["material_type"]=="HALB" and "自社製造" in rec["description"] else "F",
                created_by=USER,
                updated_by=USER,
            )
            db.add(mp)

            eccn_tag = f" [{rec['eccn']}]" if rec.get("eccn") and rec["eccn"] != "EAR99" else ""
            coo = f"({rec.get('country_of_origin','—')})" if rec.get("country_of_origin") else ""
            print(f"  + {code:15} {rec['material_type']:5} {coo:5} {rec['description'][:45]}{eccn_tag}")
            mat_created += 1

        db.commit()
        print(f"\n  品目: 新規 {mat_created}件, スキップ {mat_skipped}件")

        # ── Final summary ────────────────────────────────────────
        total_bp = db.query(BusinessPartner).filter(BusinessPartner.client_id == CLIENT_ID).count()
        total_mat = db.query(Material).filter(Material.client_id == CLIENT_ID).count()
        print(f"\n{'='*65}")
        print(f"  累計: 取引先 {total_bp}件 / 品目 {total_mat}件")
        print(f"{'='*65}\n")


if __name__ == "__main__":
    run()
