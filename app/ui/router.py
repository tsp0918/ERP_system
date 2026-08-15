"""Simple browser dashboard for ERP data browsing."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["UI"])

_HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mini Global ERP — Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  .tab-btn { @apply px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors; }
  .tab-btn.active { @apply border-indigo-500 text-indigo-600 bg-white; }
  .tab-btn:not(.active) { @apply border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300; }
  .badge { @apply inline-flex items-center px-2 py-0.5 rounded text-xs font-medium; }
  .status-OPEN       { @apply badge bg-blue-100 text-blue-800; }
  .status-COMPLETED  { @apply badge bg-green-100 text-green-800; }
  .status-BLOCKED    { @apply badge bg-red-100 text-red-800; }
  .status-RELEASED   { @apply badge bg-purple-100 text-purple-800; }
  .status-DRAFT      { @apply badge bg-gray-100 text-gray-600; }
  .check-PASSED      { @apply badge bg-emerald-100 text-emerald-800; }
  .check-BLOCKED     { @apply badge bg-red-100 text-red-700; }
  .check-PENDING     { @apply badge bg-yellow-100 text-yellow-800; }
  .check-ERROR       { @apply badge bg-orange-100 text-orange-800; }
  .check-APPROVED    { @apply badge bg-emerald-100 text-emerald-800; }
  .fefta-APPLICABLE     { @apply badge bg-red-100 text-red-700; }
  .fefta-NOT_APPLICABLE { @apply badge bg-green-100 text-green-700; }
  .fefta-UNKNOWN        { @apply badge bg-gray-100 text-gray-600; }
  .fefta-PENDING        { @apply badge bg-yellow-100 text-yellow-700; }
  .denied-true  { @apply badge bg-red-100 text-red-800; }
  .denied-false { @apply badge bg-gray-100 text-gray-500; }
  table { @apply w-full text-sm; }
  th { @apply text-left px-3 py-2 bg-gray-50 text-gray-600 font-medium text-xs uppercase tracking-wider border-b; }
  td { @apply px-3 py-2 border-b border-gray-100 text-sm; }
  tr:hover td { @apply bg-gray-50; }
</style>
</head>
<body class="bg-gray-100 min-h-screen font-sans">

<!-- Login Modal -->
<div id="loginModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 flex items-center justify-center z-50">
  <div class="bg-white rounded-xl shadow-xl p-8 w-full max-w-sm">
    <div class="text-center mb-6">
      <div class="text-3xl mb-2">🏭</div>
      <h1 class="text-xl font-bold text-gray-800">Mini Global ERP</h1>
      <p class="text-gray-500 text-sm mt-1">ダッシュボードにログイン</p>
    </div>
    <div id="loginError" class="hidden mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm"></div>
    <form id="loginForm" class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">メールアドレス</label>
        <input id="loginEmail" type="email" value="admin@example.com"
          class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">パスワード</label>
        <input id="loginPassword" type="password" value=""
          class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
      </div>
      <button type="submit"
        class="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 transition-colors">
        ログイン
      </button>
    </form>
  </div>
</div>

<!-- Main App (hidden until login) -->
<div id="app" class="hidden">

  <!-- Header -->
  <header class="bg-indigo-700 text-white shadow-md">
    <div class="max-w-screen-xl mx-auto px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-2xl">🏭</span>
        <div>
          <h1 class="text-lg font-bold leading-tight">Mini Global ERP</h1>
          <p class="text-indigo-200 text-xs">AI_TradeManagement Integration</p>
        </div>
      </div>
      <div class="flex items-center gap-4">
        <span id="userInfo" class="text-sm text-indigo-200"></span>
        <button onclick="logout()" class="text-xs bg-indigo-800 hover:bg-indigo-900 px-3 py-1 rounded-lg transition-colors">ログアウト</button>
      </div>
    </div>
  </header>

  <!-- Summary Cards -->
  <div class="max-w-screen-xl mx-auto px-4 py-4 grid grid-cols-2 md:grid-cols-5 gap-3" id="summaryCards">
  </div>

  <!-- Tab Navigation -->
  <div class="max-w-screen-xl mx-auto px-4">
    <div class="flex gap-1 border-b border-gray-200 bg-gray-100 rounded-t-lg overflow-x-auto">
      <button class="tab-btn active" onclick="showTab('materials')">📦 品目</button>
      <button class="tab-btn" onclick="showTab('partners')">🏢 取引先</button>
      <button class="tab-btn" onclick="showTab('orders')">📋 受注伝票</button>
      <button class="tab-btn" onclick="showTab('deliveries')">🚚 出荷伝票</button>
      <button class="tab-btn" onclick="showTab('billings')">🧾 請求書</button>
      <button class="tab-btn" onclick="showTab('declarations')">🛃 輸出申告</button>
      <button class="tab-btn" onclick="showTab('plan')">📊 在庫・計画</button>
      <button class="tab-btn" onclick="showTab('co')">💰 原価管理</button>
      <button class="tab-btn" onclick="showTab('qm')">🔬 品質管理</button>
      <button class="tab-btn" onclick="showTab('forecast')">📈 需給計画</button>
      <button class="tab-btn" onclick="showTab('lot')">🔗 ロット追跡</button>
      <button class="tab-btn" onclick="showTab('screening')">🚫 制裁スクリーニング</button>
    </div>
  </div>

  <!-- Tab Panels -->
  <div class="max-w-screen-xl mx-auto px-4 py-4">

    <!-- Materials -->
    <div id="tab-materials" class="tab-panel">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">品目マスター</h2>
          <div class="flex gap-2 items-center">
            <input id="mat-search" type="text" placeholder="品目コード・品名で絞込み..." oninput="filterTable('mat-table', this.value)"
              class="border border-gray-300 rounded px-2 py-1 text-sm w-48">
            <button onclick="loadMaterials()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="mat-table">
            <thead><tr>
              <th>品目コード</th><th>品目名</th><th>種別</th><th>単位</th>
              <th class="text-right">標準原価</th><th>通貨</th>
              <th>HSコード</th><th>ECCN</th><th>原産国</th><th>FEFTA判定</th>
            </tr></thead>
            <tbody id="mat-body"><tr><td colspan="10" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Business Partners -->
    <div id="tab-partners" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">取引先マスター</h2>
          <div class="flex gap-2 items-center">
            <select id="bp-role-filter" onchange="loadPartners()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">全ロール</option>
              <option value="CUSTOMER">CUSTOMER</option>
              <option value="VENDOR">VENDOR</option>
            </select>
            <input id="bp-search" type="text" placeholder="名前・国で絞込み..." oninput="filterTable('bp-table', this.value)"
              class="border border-gray-300 rounded px-2 py-1 text-sm w-48">
            <button onclick="loadPartners()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="bp-table">
            <thead><tr>
              <th>BPコード</th><th>名称</th><th>国</th><th>ロール</th>
              <th>支払条件</th><th>通貨</th><th>与信限度額</th><th>DeniedParty</th>
            </tr></thead>
            <tbody id="bp-body"><tr><td colspan="8" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Sales Orders -->
    <div id="tab-orders" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">受注伝票 (Sales Orders)</h2>
          <div class="flex gap-2 items-center">
            <select id="so-status-filter" onchange="loadOrders()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">全ステータス</option>
              <option value="OPEN">OPEN</option>
              <option value="BLOCKED">BLOCKED</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="RELEASED">RELEASED</option>
            </select>
            <input id="so-search" type="text" placeholder="受注番号・取引先で絞込み..." oninput="filterTable('so-table', this.value)"
              class="border border-gray-300 rounded px-2 py-1 text-sm w-52">
            <button onclick="loadOrders()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="so-table">
            <thead><tr>
              <th>受注番号</th><th>取引先コード</th><th>受注日</th><th>通貨</th>
              <th>合計金額</th><th>ステータス</th><th>審査結果</th><th>AI_TM case_no</th>
            </tr></thead>
            <tbody id="so-body"><tr><td colspan="8" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
        <div id="so-pagination" class="px-4 py-2 border-t flex gap-2 items-center text-sm text-gray-500"></div>
      </div>
    </div>

    <!-- Deliveries -->
    <div id="tab-deliveries" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">出荷伝票 (Deliveries)</h2>
          <button onclick="loadDeliveries()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="del-table">
            <thead><tr>
              <th>出荷番号</th><th>ステータス</th><th>受注ID</th><th>工場</th>
              <th>出荷日</th><th>AI_TM case_no</th><th>AI_TM承認</th>
            </tr></thead>
            <tbody id="del-body"><tr><td colspan="7" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Billings -->
    <div id="tab-billings" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">請求書 (Billing Documents)</h2>
          <button onclick="loadBillings()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="bill-table">
            <thead><tr>
              <th>請求番号</th><th>取引先コード</th><th>ステータス</th><th>通貨</th>
              <th>純額</th><th>税額</th><th>合計</th><th>AI_TM case_no</th>
            </tr></thead>
            <tbody id="bill-body"><tr><td colspan="8" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Export Declarations -->
    <div id="tab-declarations" class="tab-panel hidden">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">輸出申告 (Export Declarations)</h2>
          <button onclick="loadDeclarations()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="decl-table">
            <thead><tr>
              <th>申告番号</th><th>仕向国</th><th>品目コード</th><th>HSコード</th>
              <th>ECCN</th><th>数量</th><th>申告金額(USD)</th><th>ライセンス</th><th>AI_TM Ref</th>
            </tr></thead>
            <tbody id="decl-body"><tr><td colspan="9" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Plan: Stock / Supply / Demand -->
    <div id="tab-plan" class="tab-panel hidden space-y-4">

      <!-- Material Availability Table -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">品目別 在庫・需給計画 (MRP ビュー)</h2>
            <p class="text-xs text-gray-400 mt-0.5">在庫 + 発注残 + 生産供給 − 受注需要 − 製造消費</p>
          </div>
          <div class="flex gap-2 items-center">
            <select id="avail-type-filter" onchange="loadAvailability()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">全品目種別</option>
              <option value="FERT">FERT (完成品)</option>
              <option value="HALB">HALB (半製品)</option>
              <option value="ROH">ROH (原材料)</option>
              <option value="HAWA">HAWA (商品)</option>
            </select>
            <input id="avail-search" type="text" placeholder="品目コード・品名..." oninput="filterTable('avail-table', this.value)"
              class="border border-gray-300 rounded px-2 py-1 text-sm w-48">
            <button onclick="loadAvailability()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="avail-table">
            <thead><tr>
              <th>品目コード</th><th>品名</th><th>種別</th><th>単位</th>
              <th class="text-right">標準原価</th><th class="text-xs text-gray-400">原価元</th>
              <th class="text-right bg-blue-50">現在庫</th>
              <th class="text-right bg-blue-50">引当済</th>
              <th class="text-right bg-green-50">有効在庫</th>
              <th class="text-right bg-amber-50">発注残</th>
              <th class="text-right bg-amber-50">生産供給</th>
              <th class="text-right bg-red-50">SO需要</th>
              <th class="text-right bg-red-50">製造消費</th>
              <th class="text-right font-semibold">予測残</th>
            </tr></thead>
            <tbody id="avail-body"><tr><td colspan="14" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- Production Schedule -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">生産スケジュール (オープン指図)</h2>
          <div class="flex gap-2 items-center">
            <select id="sched-status-filter" onchange="loadSchedule()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">DRAFT+OPEN+RELEASED</option>
              <option value="RELEASED">RELEASED</option>
              <option value="OPEN">OPEN</option>
              <option value="DRAFT">DRAFT</option>
            </select>
            <button onclick="loadSchedule()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="sched-table">
            <thead><tr>
              <th>指図番号</th><th>品目コード</th><th>工場</th><th>ステータス</th>
              <th class="text-right">計画数量</th><th class="text-right">実績数量</th>
              <th>進捗</th><th>開始予定</th><th>完了予定</th><th>構成品目数</th>
            </tr></thead>
            <tbody id="sched-body"><tr><td colspan="10" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- CO: Controlling -->
    <div id="tab-co" class="tab-panel hidden">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Cost Centers -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
          <div class="px-4 py-3 border-b flex items-center justify-between">
            <h2 class="font-semibold text-gray-700">コストセンター</h2>
            <button onclick="loadCostCenters()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
          <div class="overflow-x-auto">
            <table id="cc-table">
              <thead><tr>
                <th>CCコード</th><th>名称</th><th>種別</th><th>作業センタ</th><th>工場</th>
              </tr></thead>
              <tbody id="cc-body"><tr><td colspan="5" class="text-center py-6 text-gray-400">読み込み中...</td></tr></tbody>
            </table>
          </div>
        </div>
        <!-- Assets -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
          <div class="px-4 py-3 border-b flex items-center justify-between">
            <h2 class="font-semibold text-gray-700">固定資産</h2>
            <button onclick="loadAssets()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
          <div class="overflow-x-auto">
            <table id="asset-table">
              <thead><tr>
                <th>資産コード</th><th>名称</th><th>区分</th><th>作業センタ</th><th>年間償却費</th><th>通貨</th>
              </tr></thead>
              <tbody id="asset-body"><tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- QM: Quality Management -->
    <div id="tab-qm" class="tab-panel hidden">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Inspection Lots -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
          <div class="px-4 py-3 border-b flex items-center justify-between">
            <h2 class="font-semibold text-gray-700">検査ロット</h2>
            <div class="flex gap-2 items-center">
              <select id="lot-status-filter" onchange="loadLots()" class="border border-gray-300 rounded px-2 py-1 text-sm">
                <option value="">全ステータス</option>
                <option value="OPEN">OPEN</option>
                <option value="IN_INSPECTION">IN_INSPECTION</option>
                <option value="PASSED">PASSED</option>
                <option value="FAILED">FAILED</option>
              </select>
              <button onclick="loadLots()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table id="lot-table">
              <thead><tr>
                <th>ロット番号</th><th>品目コード</th><th>数量</th><th>ステータス</th><th>判定</th><th>検査日</th>
              </tr></thead>
              <tbody id="lot-body"><tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr></tbody>
            </table>
          </div>
        </div>
        <!-- Quality Notifications -->
        <div class="bg-white rounded-lg shadow overflow-hidden">
          <div class="px-4 py-3 border-b flex items-center justify-between">
            <h2 class="font-semibold text-gray-700">品質通知</h2>
            <button onclick="loadQN()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
          <div class="overflow-x-auto">
            <table id="qn-table">
              <thead><tr>
                <th>通知番号</th><th>種別</th><th>品目コード</th><th>件名</th><th>重要度</th><th>ステータス</th>
              </tr></thead>
              <tbody id="qn-body"><tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Forecast: Sales Forecast vs Actual -->
    <div id="tab-forecast" class="tab-panel hidden space-y-4">
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">販売フォーキャスト vs 実績 (PIR)</h2>
            <p class="text-xs text-gray-400 mt-0.5">月次計画数量と実績受注の達成率を追跡</p>
          </div>
          <div class="flex gap-2 items-center">
            <label class="text-sm text-gray-600">年度:</label>
            <select id="fc-year" onchange="loadForecastSummary()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="2025">2025</option>
              <option value="2026" selected>2026</option>
            </select>
            <button onclick="loadForecastSummary()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="fc-summary-table">
            <thead><tr>
              <th>月</th><th>品目コード</th>
              <th class="text-right">計画数量</th><th class="text-right">実績数量</th>
              <th class="text-right">達成率</th>
              <th class="text-right">計画金額</th><th class="text-right">実績金額</th>
            </tr></thead>
            <tbody id="fc-summary-body"><tr><td colspan="7" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
      <!-- Forward Forecasts -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">販売計画 (フォーワード)</h2>
          <button onclick="loadForwardForecasts()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="fc-forward-table">
            <thead><tr>
              <th>年</th><th>月</th><th>品目コード</th>
              <th class="text-right">計画数量</th><th>単位</th>
              <th class="text-right">計画金額</th><th>通貨</th><th>バージョン</th>
            </tr></thead>
            <tbody id="fc-forward-body"><tr><td colspan="8" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Lot Traceability -->
    <div id="tab-lot" class="tab-panel hidden space-y-4">

      <!-- Origin Change Alerts -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">原産国切り替えイベント</h2>
            <p class="text-xs text-gray-400 mt-0.5">原料ロットの仕入先・原産国変更履歴と De Minimis 影響評価</p>
          </div>
          <button onclick="loadOriginChanges()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="ocl-table">
            <thead><tr>
              <th>品目コード</th><th>変更日</th><th>旧原産国</th><th>新原産国</th>
              <th>旧仕入先</th><th>新仕入先</th>
              <th>最大 De Minimis 影響</th><th>閾値超過</th>
              <th>AI_TM 通知</th><th>レビュー状態</th><th>操作</th>
            </tr></thead>
            <tbody id="ocl-body"><tr><td colspan="11" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- De Minimis BREACH Alerts -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">De Minimis アラート (EAR 25% ルール)</h2>
            <p class="text-xs text-gray-400 mt-0.5">US 原産原料を使用した製造ロットの US コンテンツ含有率評価</p>
          </div>
          <div class="flex gap-2 items-center">
            <select id="dm-filter" onchange="loadDeMinimis()" class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="BREACH">BREACH (>25%)</option>
              <option value="WARNING">WARNING (>10%)</option>
              <option value="">全て</option>
            </select>
            <button onclick="loadDeMinimis()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="dm-table">
            <thead><tr>
              <th>FGロット番号</th><th>完成品コード</th><th>製造指図番号</th>
              <th class="text-right">US含有率</th><th>アラート</th>
              <th>US原産原料</th><th>AI_TM通知</th>
            </tr></thead>
            <tbody id="dm-body"><tr><td colspan="7" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- Batch Genealogy Search -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">ロット系譜トレース</h2>
            <p class="text-xs text-gray-400 mt-0.5">ロット番号から上流（原料ロット）・下流（完成品ロット）を追跡</p>
          </div>
          <div class="flex gap-2 items-center">
            <input id="lot-search-input" type="text" placeholder="ロット番号を入力..."
              class="border border-gray-300 rounded px-2 py-1 text-sm w-56">
            <button onclick="searchLotGenealogy()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">🔍 追跡</button>
          </div>
        </div>
        <div id="genealogy-result" class="p-4 text-sm text-gray-400">ロット番号を入力してください</div>
      </div>

      <!-- US-origin Batch List -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-700">US 原産原料ロット一覧</h2>
          <button onclick="loadUSBatches()" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">↻ 更新</button>
        </div>
        <div class="overflow-x-auto">
          <table id="us-batch-table">
            <thead><tr>
              <th>ロット番号</th><th>品目コード</th><th>原産国</th><th>仕入先</th>
              <th class="text-right">数量</th><th>単位</th><th>入荷日</th><th>品質状態</th>
            </tr></thead>
            <tbody id="us-batch-body"><tr><td colspan="8" class="text-center py-6 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

    </div>

    <!-- ═══════════════════════════════════════════════════════════ -->
    <!-- Tab: 制裁スクリーニング                                       -->
    <!-- ═══════════════════════════════════════════════════════════ -->
    <div id="tab-screening" class="tab-panel hidden space-y-4">

      <!-- サマリーカード -->
      <div id="screening-summary-cards" class="grid grid-cols-2 sm:grid-cols-4 gap-3"></div>

      <!-- バルクスクリーニング操作 -->
      <div class="bg-white rounded-lg shadow p-4 flex items-center gap-4 flex-wrap">
        <div class="flex-1">
          <h2 class="font-semibold text-gray-700">一括スクリーニング</h2>
          <p class="text-xs text-gray-400 mt-0.5">全取引先を BIS Entity List / OFAC SDN / 50%ルール に照合し AI Trade Management に通知</p>
        </div>
        <label class="flex items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" id="only-unscreened" checked class="rounded"> 未スクリーニングのみ
        </label>
        <button onclick="rescreenAll()"
          class="bg-red-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-red-700 transition-colors">
          🔍 スクリーニング実行
        </button>
        <button onclick="loadScreening()"
          class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-3 py-1 rounded border border-indigo-200">
          ↻ 更新
        </button>
      </div>

      <!-- 取引先一覧 (スクリーニングステータス付き) -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">取引先スクリーニング状況</h2>
            <p class="text-xs text-gray-400 mt-0.5">登録済み取引先のリスト照合結果</p>
          </div>
          <div class="flex gap-2">
            <select id="sc-status-filter" onchange="loadScreeningBPs()"
              class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">全件</option>
              <option value="BLOCKED">🔴 BLOCKED</option>
              <option value="FLAGGED">🟠 FLAGGED</option>
              <option value="CLEARED">✅ CLEARED</option>
              <option value="UNSCREENED">⬜ 未スクリーニング</option>
            </select>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="sc-bp-table">
            <thead><tr>
              <th>BPコード</th><th>会社名</th><th>国</th><th>役割</th>
              <th>スクリーニング状態</th><th>照合リスト</th><th>制裁理由 (要約)</th>
              <th>50%ルール</th><th>AI_TM 参照</th><th>最終スクリーニング日</th><th>操作</th>
            </tr></thead>
            <tbody id="sc-bp-body"><tr><td colspan="11" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- スクリーニング監査ログ -->
      <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-gray-700">スクリーニング監査ログ</h2>
            <p class="text-xs text-gray-400 mt-0.5">AI_TM への Webhook 通知履歴を含む全照合記録</p>
          </div>
          <div class="flex gap-2">
            <label class="flex items-center gap-1 text-xs text-gray-600">
              <input type="checkbox" id="sc-fifty-only" onchange="loadScreeningLog()" class="rounded"> 50%ルールのみ
            </label>
            <select id="sc-log-filter" onchange="loadScreeningLog()"
              class="border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">全件</option>
              <option value="CRITICAL">🔴 CRITICAL</option>
              <option value="match">🟠 match</option>
              <option value="possible_match">🟡 possible_match</option>
              <option value="no_match">✅ no_match</option>
            </select>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table id="sc-log-table">
            <thead><tr>
              <th>ID</th><th>BPコード</th><th>会社名</th><th>国</th>
              <th>照合結果</th><th>スコア</th><th>照合リスト</th><th>照合企業名</th>
              <th>50%ルール</th><th>親会社</th><th>AI_TM 参照</th><th>スクリーニング日時</th>
            </tr></thead>
            <tbody id="sc-log-body"><tr><td colspan="12" class="text-center py-8 text-gray-400">読み込み中...</td></tr></tbody>
          </table>
        </div>
      </div>

    </div>

  </div><!-- /tab content -->
</div><!-- /app -->

<script>
const BASE = '';
let TOKEN = sessionStorage.getItem('erp_token') || '';
let SO_SKIP = 0;
const SO_LIMIT = 20;

// ── Auth ─────────────────────────────────────────────────────
document.getElementById('loginForm').addEventListener('submit', async e => {
  e.preventDefault();
  const email = document.getElementById('loginEmail').value;
  const pass  = document.getElementById('loginPassword').value;
  const err   = document.getElementById('loginError');
  err.classList.add('hidden');
  try {
    const fd = new FormData();
    fd.append('username', email);
    fd.append('password', pass);
    const res = await fetch('/auth/token', {method:'POST', body:fd});
    if (!res.ok) throw new Error((await res.json()).detail || 'ログイン失敗');
    const data = await res.json();
    TOKEN = data.access_token;
    sessionStorage.setItem('erp_token', TOKEN);
    document.getElementById('loginModal').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('userInfo').textContent = `${data.email}  |  ${data.client_id}`;
    initApp();
  } catch(ex) {
    err.textContent = ex.message;
    err.classList.remove('hidden');
  }
});

function logout() {
  sessionStorage.removeItem('erp_token');
  location.reload();
}

function hdrs() { return {'Authorization': `Bearer ${TOKEN}`}; }

async function apiFetch(path, params={}, method='GET', body=null) {
  const url = new URL(BASE + path, location.href);
  if (method === 'GET') {
    Object.entries(params).forEach(([k,v]) => v != null && v !== '' && url.searchParams.set(k, v));
  }
  const opts = {method, headers: hdrs()};
  if (body) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const res = await fetch(url, opts);
  if (res.status === 401) { logout(); return null; }
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

// ── Init ─────────────────────────────────────────────────────
async function initApp() {
  await loadSummary();
  loadMaterials();
}

async function loadSummary() {
  try {
    const [mats, bps, sos, dels, bills] = await Promise.all([
      apiFetch('/mdm/materials', {limit:1}),
      apiFetch('/mdm/business-partners', {limit:1}),
      apiFetch('/sd/sales-orders', {limit:1}),
      apiFetch('/sd/deliveries', {limit:1}),
      apiFetch('/sd/billing', {limit:1}),
    ]);
    const cards = [
      {label:'品目', value: mats?.total ?? '—', icon:'📦', color:'indigo'},
      {label:'取引先', value: bps?.total ?? '—', icon:'🏢', color:'blue'},
      {label:'受注伝票', value: sos?.total ?? '—', icon:'📋', color:'violet'},
      {label:'出荷伝票', value: dels?.total ?? '—', icon:'🚚', color:'emerald'},
      {label:'請求書', value: bills?.total ?? '—', icon:'🧾', color:'amber'},
    ];
    document.getElementById('summaryCards').innerHTML = cards.map(c => `
      <div class="bg-white rounded-lg shadow p-4 flex items-center gap-3">
        <div class="text-2xl">${c.icon}</div>
        <div>
          <div class="text-2xl font-bold text-gray-800">${c.value}</div>
          <div class="text-xs text-gray-500">${c.label}</div>
        </div>
      </div>`).join('');
  } catch(e) { console.warn('summary load failed', e); }
}

// ── Tabs ─────────────────────────────────────────────────────
const LOADERS = {
  materials: loadMaterials, partners: loadPartners,
  orders: loadOrders, deliveries: loadDeliveries,
  billings: loadBillings, declarations: loadDeclarations,
  plan: loadPlan, co: loadCO, qm: loadQM,
  forecast: loadForecast,
  lot: loadLot,
  screening: loadScreening,
};

function showTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.remove('hidden');
  event.currentTarget.classList.add('active');
  if (LOADERS[name]) LOADERS[name]();
}

// ── Helpers ──────────────────────────────────────────────────
function badge(cls, text) { return `<span class="${cls}">${text || '—'}</span>`; }
function statusBadge(s)   { return badge('status-' + (s||'DRAFT'), s||'—'); }
function checkBadge(s)    { return badge('check-' + (s||''), s||'—'); }
function feftaBadge(s)    { return badge('fefta-' + (s||'UNKNOWN'), s||'UNKNOWN'); }

function fmt(n, digits=0) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', {minimumFractionDigits:digits, maximumFractionDigits:digits});
}

function filterTable(tableId, q) {
  const rows = document.querySelectorAll(`#${tableId} tbody tr`);
  const low = q.toLowerCase();
  rows.forEach(r => {
    r.style.display = r.textContent.toLowerCase().includes(low) ? '' : 'none';
  });
}

// ── Materials ─────────────────────────────────────────────────
async function loadMaterials() {
  const body = document.getElementById('mat-body');
  body.innerHTML = '<tr><td colspan="10" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/mdm/materials', {limit:500});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="10" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(m => `<tr>
      <td class="font-mono text-xs">${m.material_code}</td>
      <td>${m.description}</td>
      <td class="text-xs text-gray-500">${m.material_type}</td>
      <td class="text-xs text-gray-500">${m.base_unit}</td>
      <td class="text-right font-mono text-xs">${m.standard_price ? fmt(m.standard_price, 0) : '—'}</td>
      <td class="text-xs text-gray-400">${m.currency||'—'}</td>
      <td class="font-mono text-xs">${m.hs_code||'—'}</td>
      <td class="font-mono text-xs">${m.eccn||'—'}</td>
      <td class="text-xs">${m.country_of_origin||'—'}</td>
      <td>${feftaBadge(m.fefta_judgment)}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Business Partners ─────────────────────────────────────────
async function loadPartners() {
  const body = document.getElementById('bp-body');
  body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  const role = document.getElementById('bp-role-filter').value;
  try {
    const data = await apiFetch('/mdm/business-partners', {limit:500, role: role||null});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(bp => `<tr>
      <td class="font-mono text-xs">${bp.bp_code}</td>
      <td>${bp.name}</td>
      <td><span class="inline-block text-xs font-medium px-1.5 py-0.5 rounded bg-gray-100">${bp.country}</span></td>
      <td class="text-xs text-gray-600">${bp.roles}</td>
      <td class="text-xs">${bp.payment_terms||'—'}</td>
      <td class="text-xs">${bp.currency||'—'}</td>
      <td class="text-right text-xs">${bp.credit_limit ? fmt(bp.credit_limit) : '—'}</td>
      <td>${bp.is_denied_party
          ? badge('denied-true','⛔ DENIED')
          : badge('denied-false','✓ Clear')}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Sales Orders ──────────────────────────────────────────────
async function loadOrders(skip) {
  if (skip !== undefined) SO_SKIP = skip;
  const body = document.getElementById('so-body');
  body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  const statusFilter = document.getElementById('so-status-filter').value;
  try {
    const data = await apiFetch('/sd/sales-orders', {limit: SO_LIMIT, skip: SO_SKIP, status: statusFilter||null});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(so => `<tr>
      <td class="font-mono text-xs font-medium">${so.document_number}</td>
      <td class="text-xs">${so.customer_code}</td>
      <td class="text-xs text-gray-500">${so.document_date}</td>
      <td class="text-xs text-gray-500">${so.currency}</td>
      <td class="text-right font-mono text-xs">${fmt(so.total_amount, 2)}</td>
      <td>${statusBadge(so.status)}</td>
      <td>${checkBadge(so.export_check_status)}</td>
      <td class="font-mono text-xs text-gray-400">${so.export_check_ref||'—'}</td>
    </tr>`).join('');
    // Pagination
    const total = data.total;
    const pg = document.getElementById('so-pagination');
    pg.innerHTML = `<span>${SO_SKIP+1}〜${Math.min(SO_SKIP+SO_LIMIT, total)} / ${total} 件</span>
      ${SO_SKIP > 0 ? `<button onclick="loadOrders(${SO_SKIP - SO_LIMIT})" class="ml-2 px-2 py-0.5 rounded border text-xs hover:bg-gray-100">← 前へ</button>` : ''}
      ${SO_SKIP + SO_LIMIT < total ? `<button onclick="loadOrders(${SO_SKIP + SO_LIMIT})" class="ml-2 px-2 py-0.5 rounded border text-xs hover:bg-gray-100">次へ →</button>` : ''}`;
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Deliveries ────────────────────────────────────────────────
async function loadDeliveries() {
  const body = document.getElementById('del-body');
  body.innerHTML = '<tr><td colspan="7" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/sd/deliveries', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="7" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(d => `<tr>
      <td class="font-mono text-xs font-medium">${d.document_number}</td>
      <td>${statusBadge(d.status)}</td>
      <td class="text-xs text-gray-500">${d.sales_order_id}</td>
      <td class="text-xs text-gray-500">${d.plant_code||'—'}</td>
      <td class="text-xs text-gray-500">${d.actual_delivery_date||'—'}</td>
      <td class="font-mono text-xs text-gray-400">${d.aitm_case_no||'—'}</td>
      <td>${d.aitm_approval_status ? checkBadge(d.aitm_approval_status) : badge('badge bg-gray-100 text-gray-400','—')}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Billings ──────────────────────────────────────────────────
async function loadBillings() {
  const body = document.getElementById('bill-body');
  body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/sd/billing', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(b => `<tr>
      <td class="font-mono text-xs font-medium">${b.document_number}</td>
      <td class="text-xs">${b.customer_code}</td>
      <td>${statusBadge(b.status)}</td>
      <td class="text-xs text-gray-500">${b.currency}</td>
      <td class="text-right font-mono text-xs">${fmt(b.net_amount,2)}</td>
      <td class="text-right font-mono text-xs">${fmt(b.tax_amount,2)}</td>
      <td class="text-right font-mono text-xs font-medium">${fmt(b.gross_amount,2)}</td>
      <td class="font-mono text-xs text-gray-400">${b.aitm_case_no||'—'}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Export Declarations ───────────────────────────────────────
async function loadDeclarations() {
  const body = document.getElementById('decl-body');
  body.innerHTML = '<tr><td colspan="9" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/gts/export-declarations', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="9" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(d => `<tr>
      <td class="font-mono text-xs font-medium">${d.declaration_number||'—'}</td>
      <td><span class="inline-block text-xs font-medium px-1.5 py-0.5 rounded bg-gray-100">${d.destination_country||'—'}</span></td>
      <td class="font-mono text-xs">${d.material_code||'—'}</td>
      <td class="font-mono text-xs">${d.hs_code||'—'}</td>
      <td class="font-mono text-xs">${d.eccn||'—'}</td>
      <td class="text-right text-xs">${fmt(d.quantity)}</td>
      <td class="text-right font-mono text-xs">${fmt(d.declared_value_usd,2)}</td>
      <td class="text-xs text-gray-600">${d.license_type||'—'}</td>
      <td class="font-mono text-xs text-gray-400">${d.ai_tm_transaction_id||'—'}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="9" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Plan: Stock / Supply / Demand ────────────────────────────
function loadPlan() { loadAvailability(); loadSchedule(); }

const STATUS_ORDER_COLOR = {RELEASED:'bg-purple-100 text-purple-800', OPEN:'bg-blue-100 text-blue-800', DRAFT:'bg-gray-100 text-gray-600', COMPLETED:'bg-green-100 text-green-800', CANCELLED:'bg-red-100 text-red-700'};

async function loadAvailability() {
  const body = document.getElementById('avail-body');
  body.innerHTML = '<tr><td colspan="14" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  const matType = document.getElementById('avail-type-filter').value;
  try {
    const data = await apiFetch('/mm/material-availability', {limit:500, material_type: matType||null});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="14" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(m => {
      const proj = Number(m.projected_qty);
      const projColor = proj < 0 ? 'text-red-600 font-semibold' : proj === 0 ? 'text-gray-400' : 'text-green-700';
      const costSrcColor = m.cost_source === 'CCS' ? 'bg-indigo-50 text-indigo-700' : m.cost_source === 'MDM' ? 'bg-gray-100 text-gray-600' : 'bg-gray-50 text-gray-400';
      return `<tr>
        <td class="font-mono text-xs font-medium">${m.material_code}</td>
        <td class="text-sm">${m.description}</td>
        <td class="text-xs text-gray-500">${m.material_type}</td>
        <td class="text-xs text-gray-400">${m.base_unit}</td>
        <td class="text-right font-mono text-xs">${m.standard_cost ? fmt(m.standard_cost, 0) : '—'}</td>
        <td class="text-center"><span class="badge ${costSrcColor} text-xs">${m.cost_source}</span></td>
        <td class="text-right font-mono text-xs bg-blue-50">${fmt(m.stock_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-blue-50 text-gray-400">${fmt(m.reserved_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-green-50 font-medium">${fmt(m.available_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-amber-50">${fmt(m.open_po_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-amber-50">${fmt(m.in_production_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-red-50">${fmt(m.open_so_qty, 1)}</td>
        <td class="text-right font-mono text-xs bg-red-50">${fmt(m.component_demand_qty, 1)}</td>
        <td class="text-right font-mono text-xs ${projColor}">${fmt(proj, 1)}</td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="14" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function loadSchedule() {
  const body = document.getElementById('sched-body');
  body.innerHTML = '<tr><td colspan="10" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  const st = document.getElementById('sched-status-filter').value;
  try {
    const data = await apiFetch('/pp/schedule', {limit:100, status: st||null});
    if (!data?.length) { body.innerHTML = '<tr><td colspan="10" class="text-center py-6 text-gray-400">データなし (全指図がCOMPLETEDまたはCANCELLED)</td></tr>'; return; }
    body.innerHTML = data.map(o => {
      const sc = STATUS_ORDER_COLOR[o.status] || 'bg-gray-100 text-gray-600';
      const prog = Math.min(100, Math.max(0, o.progress_percent));
      const barColor = o.status === 'RELEASED' ? 'bg-purple-500' : o.status === 'OPEN' ? 'bg-blue-400' : 'bg-gray-300';
      return `<tr>
        <td class="font-mono text-xs font-medium">${o.order_number}</td>
        <td class="font-mono text-xs">${o.material_code}</td>
        <td class="text-xs text-gray-500">${o.plant_code}</td>
        <td><span class="badge ${sc}">${o.status}</span></td>
        <td class="text-right font-mono text-xs">${fmt(o.target_quantity, 0)}</td>
        <td class="text-right font-mono text-xs">${fmt(o.actual_quantity, 0)}</td>
        <td class="w-28">
          <div class="flex items-center gap-1">
            <div class="flex-1 bg-gray-100 rounded h-2">
              <div class="${barColor} h-2 rounded" style="width:${prog}%"></div>
            </div>
            <span class="text-xs text-gray-500 w-8 text-right">${prog.toFixed(0)}%</span>
          </div>
        </td>
        <td class="text-xs text-gray-500">${o.scheduled_start ? o.scheduled_start.substring(0,10) : '—'}</td>
        <td class="text-xs text-gray-500">${o.scheduled_end ? o.scheduled_end.substring(0,10) : '—'}</td>
        <td class="text-center text-xs text-gray-500">${o.components.length}</td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="10" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── CO: Controlling ───────────────────────────────────────────
function loadCO() { loadCostCenters(); loadAssets(); }

async function loadCostCenters() {
  const body = document.getElementById('cc-body');
  body.innerHTML = '<tr><td colspan="5" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/co/cost-centers', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="5" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(cc => `<tr>
      <td class="font-mono text-xs font-medium">${cc.cost_center_code}</td>
      <td>${cc.name}</td>
      <td class="text-xs text-gray-500">${cc.cost_center_type}</td>
      <td class="font-mono text-xs text-gray-500">${cc.work_center_code||'—'}</td>
      <td class="text-xs text-gray-500">${cc.plant_code||'—'}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function loadAssets() {
  const body = document.getElementById('asset-body');
  body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/co/assets', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(a => `<tr>
      <td class="font-mono text-xs font-medium">${a.asset_code}</td>
      <td>${a.description}</td>
      <td class="text-xs text-gray-500">${a.asset_class}</td>
      <td class="font-mono text-xs text-gray-500">${a.work_center_code||'—'}</td>
      <td class="text-right font-mono text-xs">${fmt(a.annual_depreciation)}</td>
      <td class="text-xs text-gray-400">${a.currency}</td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── QM: Quality Management ────────────────────────────────────
function loadQM() { loadLots(); loadQN(); }

const LOT_STATUS_STYLE = {PASSED:'bg-emerald-100 text-emerald-800', FAILED:'bg-red-100 text-red-700', IN_INSPECTION:'bg-blue-100 text-blue-800', OPEN:'bg-gray-100 text-gray-600', PARTIAL:'bg-yellow-100 text-yellow-800'};
const QN_SEVERITY_STYLE = {CRITICAL:'bg-red-100 text-red-800', HIGH:'bg-orange-100 text-orange-800', MEDIUM:'bg-yellow-100 text-yellow-800', LOW:'bg-gray-100 text-gray-600'};

async function loadLots() {
  const body = document.getElementById('lot-body');
  body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  const statusFilter = document.getElementById('lot-status-filter').value;
  try {
    const data = await apiFetch('/qm/lots', {limit:200, lot_status: statusFilter||null});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(l => {
      const sc = LOT_STATUS_STYLE[l.lot_status] || 'bg-gray-100 text-gray-600';
      const jc = l.overall_judgment==='PASS' ? 'bg-emerald-100 text-emerald-800' : l.overall_judgment==='FAIL' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-500';
      return `<tr>
        <td class="font-mono text-xs font-medium">${l.lot_number}</td>
        <td class="font-mono text-xs">${l.material_code}</td>
        <td class="text-right text-xs">${fmt(l.lot_quantity)} ${l.quantity_unit||''}</td>
        <td><span class="badge ${sc}">${l.lot_status}</span></td>
        <td>${l.overall_judgment ? `<span class="badge ${jc}">${l.overall_judgment}</span>` : '—'}</td>
        <td class="text-xs text-gray-500">${l.inspection_date||'—'}</td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function loadQN() {
  const body = document.getElementById('qn-body');
  body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/qm/notifications', {limit:200});
    if (!data?.items?.length) { body.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.items.map(qn => {
      const sc = QN_SEVERITY_STYLE[qn.severity] || 'bg-gray-100 text-gray-600';
      const stc = qn.status==='CLOSED' ? 'bg-gray-100 text-gray-500' : qn.status==='IN_PROGRESS' ? 'bg-blue-100 text-blue-800' : 'bg-yellow-100 text-yellow-800';
      return `<tr>
        <td class="font-mono text-xs font-medium">${qn.notification_number}</td>
        <td class="text-xs text-gray-600">${qn.notification_type}</td>
        <td class="font-mono text-xs">${qn.material_code||'—'}</td>
        <td class="text-sm">${qn.subject}</td>
        <td><span class="badge ${sc}">${qn.severity}</span></td>
        <td><span class="badge ${stc}">${qn.status}</span></td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Forecast ─────────────────────────────────────────────────
function loadForecast() { loadForecastSummary(); loadForwardForecasts(); }

async function loadForecastSummary() {
  const year = document.getElementById('fc-year')?.value || new Date().getFullYear();
  const body = document.getElementById('fc-summary-body');
  body.innerHTML = '<tr><td colspan="7" class="text-center py-8 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch(`/sd/forecasts/summary?year=${year}`);
    if (!data?.length) { body.innerHTML = '<tr><td colspan="7" class="text-center py-8 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.map(f => {
      const att = f.attainment_pct;
      const attCls = att == null ? '' : att >= 100 ? 'text-green-700 font-semibold' : att >= 80 ? 'text-amber-600 font-semibold' : 'text-red-600 font-bold';
      const bar = att == null ? '—' : `<div class="flex items-center gap-1"><div class="w-20 bg-gray-200 rounded-full h-2"><div class="h-2 rounded-full ${att>=100?'bg-green-500':att>=80?'bg-amber-400':'bg-red-500'}" style="width:${Math.min(att,100)}%"></div></div><span class="${attCls} text-xs">${att}%</span></div>`;
      return `<tr>
        <td class="text-sm font-medium">${f.year}-${String(f.month).padStart(2,'0')}</td>
        <td class="font-mono text-xs">${f.material_code}</td>
        <td class="text-right font-mono text-sm">${fmt(f.forecast_qty,1)}</td>
        <td class="text-right font-mono text-sm">${fmt(f.actual_qty,1)}</td>
        <td>${bar}</td>
        <td class="text-right text-sm text-gray-600">${fmt(f.forecast_value)}</td>
        <td class="text-right text-sm">${fmt(f.actual_value)}</td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function loadForwardForecasts() {
  const body = document.getElementById('fc-forward-body');
  body.innerHTML = '<tr><td colspan="8" class="text-center py-8 text-gray-400">読み込み中...</td></tr>';
  try {
    const now2 = new Date();
    // Fetch forecasts for current year + next year to cover all forward months
    const [d1, d2] = await Promise.all([
      apiFetch(`/sd/forecasts?year=${now2.getFullYear()}&limit=500`),
      apiFetch(`/sd/forecasts?year=${now2.getFullYear()+1}&limit=500`),
    ]);
    const data = [...(Array.isArray(d1)?d1:[]), ...(Array.isArray(d2)?d2:[])];
    // Show next 6 months
    const nextMonths = [];
    const now = new Date();
    for (let i=1; i<=6; i++) {
      const d = new Date(now.getFullYear(), now.getMonth()+i, 1);
      nextMonths.push({y: d.getFullYear(), m: d.getMonth()+1});
    }
    const forward = (Array.isArray(data) ? data : data?.items || []).filter(f =>
      nextMonths.some(nm => nm.y===f.year && nm.m===f.month)
    );
    if (!forward.length) { body.innerHTML = '<tr><td colspan="8" class="text-center py-8 text-gray-400">フォワード計画なし</td></tr>'; return; }
    body.innerHTML = forward.map(f => `<tr>
      <td class="text-sm">${f.year}</td>
      <td class="text-sm">${String(f.month).padStart(2,'0')}</td>
      <td class="font-mono text-xs">${f.material_code}</td>
      <td class="text-right font-mono text-sm text-blue-700 font-medium">${fmt(f.forecast_quantity,1)}</td>
      <td class="text-xs text-gray-500">${f.quantity_unit}</td>
      <td class="text-right text-sm text-gray-600">${fmt(f.forecast_value)}</td>
      <td class="text-xs text-gray-500">${f.currency}</td>
      <td><span class="badge bg-indigo-100 text-indigo-700">${f.version}</span></td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-red-400">エラー: ${e.message}</td></tr>`; }
}

// ── Lot Traceability ─────────────────────────────────────────
function loadLot() { loadOriginChanges(); loadDeMinimis(); loadUSBatches(); }

async function loadOriginChanges() {
  const body = document.getElementById('ocl-body');
  body.innerHTML = '<tr><td colspan="11" class="text-center py-8 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/gts/origin-change-log');
    if (!data?.length) { body.innerHTML = '<tr><td colspan="11" class="text-center py-8 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.map(ev => {
      const breach = ev.exceeds_threshold;
      const impactCls = breach ? 'text-red-600 font-bold' : 'text-amber-600 font-medium';
      const breachBadge = breach
        ? '<span class="badge bg-red-100 text-red-700">BREACH</span>'
        : '<span class="badge bg-green-100 text-green-700">OK</span>';
      const aitm = ev.ai_tm_notification_sent
        ? `<span class="badge bg-green-100 text-green-700">送信済</span>`
        : `<button onclick="notifyAITM(${ev.id})" class="text-xs bg-red-50 hover:bg-red-100 text-red-700 px-2 py-0.5 rounded border border-red-200">AI_TM 通知</button>`;
      const rvCls = ev.review_status === 'ACTION_REQUIRED' ? 'bg-red-100 text-red-700'
                  : ev.review_status === 'PENDING' ? 'bg-yellow-100 text-yellow-700'
                  : 'bg-gray-100 text-gray-600';
      return `<tr class="${breach ? 'bg-red-50' : ''}">
        <td class="font-mono text-xs font-medium">${ev.material_code}</td>
        <td class="text-sm">${ev.effective_date}</td>
        <td><span class="badge bg-blue-100 text-blue-700">${ev.from_country}</span></td>
        <td><span class="badge bg-orange-100 text-orange-700">${ev.to_country}</span></td>
        <td class="text-xs text-gray-500">${ev.old_vendor_code||'—'}</td>
        <td class="text-xs text-gray-500">${ev.new_vendor_code||'—'}</td>
        <td class="${impactCls} text-right text-sm">${ev.max_deminimis_impact_pct!=null ? ev.max_deminimis_impact_pct+'%' : '—'}</td>
        <td>${breachBadge}</td>
        <td>${aitm}</td>
        <td><span class="badge ${rvCls} text-xs">${ev.review_status}</span></td>
        <td><button onclick="loadBatchGenealogy('${ev.last_old_batch_code||ev.first_new_batch_code||''}')" class="text-xs text-indigo-600 hover:underline">系譜</button></td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="11" class="text-center py-8 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function notifyAITM(logId) {
  try {
    const result = await apiFetch(`/gts/origin-change-log/${logId}/notify-aitm`, {}, 'POST');
    alert(`AI_TM 通知完了\nCase Ref: ${result.ai_tm_case_ref}\n通知アセスメント数: ${result.breach_assessments_notified}`);
    loadOriginChanges();
    loadDeMinimis();
  } catch(e) { alert('エラー: ' + e.message); }
}

async function loadDeMinimis() {
  const level = document.getElementById('dm-filter')?.value || 'BREACH';
  const body = document.getElementById('dm-body');
  body.innerHTML = '<tr><td colspan="7" class="text-center py-8 text-gray-400">読み込み中...</td></tr>';
  try {
    const url = level ? `/gts/deminimis?alert_level=${level}&limit=100` : '/gts/deminimis?limit=100';
    const data = await apiFetch(url);
    if (!data?.length) { body.innerHTML = '<tr><td colspan="7" class="text-center py-8 text-gray-400">データなし</td></tr>'; return; }
    body.innerHTML = data.map(a => {
      const pct = a.us_content_pct;
      const alertCls = a.alert_level === 'BREACH' ? 'bg-red-100 text-red-700'
                     : a.alert_level === 'WARNING' ? 'bg-amber-100 text-amber-700'
                     : 'bg-gray-100 text-gray-600';
      const bar = `<div class="flex items-center gap-1"><div class="w-24 bg-gray-200 rounded-full h-2"><div class="h-2 rounded-full ${pct>=25?'bg-red-500':'bg-amber-400'}" style="width:${Math.min(pct/50*100,100)}%"></div></div><span class="text-xs font-bold ${pct>=25?'text-red-600':'text-amber-600'}">${pct}%</span></div>`;
      const comps = a.us_components.map(c => `${c.material_code}(${c.pct_of_product}%)`).join(', ');
      const notified = a.ai_tm_notified
        ? `<span class="badge bg-green-100 text-green-700 text-xs">送信済</span>`
        : '<span class="badge bg-gray-100 text-gray-400 text-xs">未通知</span>';
      return `<tr class="${a.alert_level==='BREACH'?'bg-red-50':''}">
        <td class="font-mono text-xs cursor-pointer text-indigo-600 hover:underline" onclick="loadBatchGenealogy('${a.fg_batch_code}')">${a.fg_batch_code}</td>
        <td class="font-mono text-xs">${a.fg_material_code}</td>
        <td class="font-mono text-xs">${a.process_order_number}</td>
        <td>${bar}</td>
        <td><span class="badge ${alertCls}">${a.alert_level}</span></td>
        <td class="text-xs text-gray-600 max-w-xs truncate">${comps}</td>
        <td>${notified}</td>
      </tr>`;
    }).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-red-400">エラー: ${e.message}</td></tr>`; }
}

async function loadUSBatches() {
  const body = document.getElementById('us-batch-body');
  body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">読み込み中...</td></tr>';
  try {
    const data = await apiFetch('/mm/batches?country_of_origin=US&source_type=PURCHASED&limit=100');
    if (!data?.length) { body.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-400">US 原産ロットなし</td></tr>'; return; }
    body.innerHTML = data.map(b => `<tr>
      <td class="font-mono text-xs font-medium cursor-pointer text-indigo-600 hover:underline" onclick="loadBatchGenealogy('${b.batch_code}')">${b.batch_code}</td>
      <td class="font-mono text-xs">${b.material_code}</td>
      <td><span class="badge bg-orange-100 text-orange-700">${b.country_of_origin}</span></td>
      <td class="text-xs text-gray-600">${b.vendor_code||'—'}</td>
      <td class="text-right font-mono text-sm">${fmt(b.quantity,1)}</td>
      <td class="text-xs text-gray-500">${b.unit}</td>
      <td class="text-sm">${b.production_date||'—'}</td>
      <td><span class="badge ${b.quality_status==='RELEASED'?'bg-green-100 text-green-700':'bg-yellow-100 text-yellow-700'}">${b.quality_status}</span></td>
    </tr>`).join('');
  } catch(e) { body.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400">エラー: ${e.message}</td></tr>`; }
}

function searchLotGenealogy() {
  const code = document.getElementById('lot-search-input')?.value?.trim();
  if (code) loadBatchGenealogy(code);
}

async function loadBatchGenealogy(batchCode) {
  if (!batchCode) return;
  const el = document.getElementById('genealogy-result');
  el.innerHTML = '<span class="text-gray-400">読み込み中...</span>';
  // Also fill the search input
  const input = document.getElementById('lot-search-input');
  if (input) input.value = batchCode;
  try {
    const d = await apiFetch(`/mm/batches/${encodeURIComponent(batchCode)}/genealogy`);
    const coo = d.country_of_origin;
    const cooEl = `<span class="badge ${coo==='US'?'bg-orange-100 text-orange-700':'bg-blue-100 text-blue-700'}">${coo||'?'}</span>`;
    let html = `<div class="space-y-3">
      <div class="font-semibold">📦 <span class="font-mono">${d.batch_code}</span> (${d.material_code}) ${cooEl}
        <span class="text-xs text-gray-400 ml-2">製造日: ${d.production_date||'?'}</span></div>`;

    if (d.parents.length) {
      html += `<div class="ml-4"><div class="text-xs text-gray-500 mb-1">▲ 上流原料ロット (使用した原材料)</div>`;
      for (const p of d.parents) {
        const pc = p.country_of_origin;
        const pTag = `<span class="badge ${pc==='US'?'bg-orange-100 text-orange-700 font-bold':'bg-gray-100 text-gray-600'}">${pc||'?'}</span>`;
        html += `<div class="flex items-center gap-2 py-1 border-l-2 border-gray-300 pl-3">
          <span class="font-mono text-xs cursor-pointer text-indigo-600 hover:underline" onclick="loadBatchGenealogy('${p.batch_code}')">${p.batch_code}</span>
          <span class="text-xs text-gray-500">(${p.material_code})</span>
          ${pTag}
          <span class="text-xs text-gray-400">${fmt(p.quantity,1)} ${p.unit}</span>
          ${pc==='US'?'<span class="text-xs text-red-600 font-bold">⚠ US 原産</span>':''}
        </div>`;
      }
      html += '</div>';
    }

    if (d.children.length) {
      html += `<div class="ml-4"><div class="text-xs text-gray-500 mb-1">▼ 下流完成品ロット (このロットを使用した製品)</div>`;
      for (const c of d.children) {
        html += `<div class="flex items-center gap-2 py-1 border-l-2 border-green-300 pl-3">
          <span class="font-mono text-xs cursor-pointer text-indigo-600 hover:underline" onclick="loadBatchGenealogy('${c.batch_code}')">${c.batch_code}</span>
          <span class="text-xs text-gray-500">(${c.material_code})</span>
          <span class="text-xs text-gray-400">消費量: ${fmt(c.quantity,1)} ${c.unit}</span>
        </div>`;
      }
      html += '</div>';
    }

    if (!d.parents.length && !d.children.length) {
      html += '<div class="text-xs text-gray-400 ml-4">系譜リンクなし（単独ロット）</div>';
    }
    html += '</div>';
    el.innerHTML = html;
    // Switch to lot tab if not already there
    const tab = document.getElementById('tab-lot');
    if (tab) tab.classList.remove('hidden');
  } catch(e) { el.innerHTML = `<span class="text-red-400">エラー: ${e.message}</span>`; }
}

// ── Denied Party Screening ────────────────────────────────────
function loadScreening() { loadScreeningBPs(); loadScreeningLog(); loadScreeningSummary(); }

async function loadScreeningSummary() {
  try {
    const bps = await apiFetch('/mdm/business-partners', {limit: 500});
    const all = bps?.items ?? [];
    const blocked = all.filter(b => b.screening_status === 'BLOCKED').length;
    const flagged = all.filter(b => b.screening_status === 'FLAGGED').length;
    const cleared = all.filter(b => b.screening_status === 'CLEARED').length;
    const unscreened = all.filter(b => b.screening_status === 'UNSCREENED' || !b.screening_status).length;
    const fifty = all.filter(b => b.fifty_pct_rule_triggered).length;
    const cards = [
      {icon:'🔴', label:'BLOCKED (完全禁止)', value: blocked, color:'red'},
      {icon:'🟠', label:'FLAGGED (要調査)', value: flagged, color:'orange'},
      {icon:'✅', label:'CLEARED (クリア)', value: cleared, color:'green'},
      {icon:'⚖️', label:'50%ルール適用', value: fifty, color:'purple'},
    ];
    document.getElementById('screening-summary-cards').innerHTML = cards.map(c => `
      <div class="bg-white rounded-lg shadow p-4 flex items-center gap-3 border-l-4 border-${c.color}-400">
        <div class="text-2xl">${c.icon}</div>
        <div>
          <div class="text-2xl font-bold text-gray-800">${c.value}</div>
          <div class="text-xs text-gray-500">${c.label}</div>
        </div>
      </div>`).join('');
  } catch(e) { console.warn('screening summary failed', e); }
}

async function loadScreeningBPs() {
  const tbody = document.getElementById('sc-bp-body');
  const statusFilter = document.getElementById('sc-status-filter').value;
  try {
    const data = await apiFetch('/mdm/business-partners', {limit: 200});
    let items = data?.items ?? [];
    if (statusFilter) items = items.filter(b => b.screening_status === statusFilter);

    const scBadge = s => {
      const map = {
        BLOCKED: 'bg-red-100 text-red-800 font-semibold',
        FLAGGED: 'bg-orange-100 text-orange-800',
        CLEARED: 'bg-green-100 text-green-800',
        UNSCREENED: 'bg-gray-100 text-gray-500',
      };
      return `<span class="badge ${map[s] || 'bg-gray-100 text-gray-500'}">${s || 'UNSCREENED'}</span>`;
    };

    tbody.innerHTML = items.length === 0 ? '<tr><td colspan="11" class="text-center py-8 text-gray-400">該当なし</td></tr>'
      : items.map(b => `<tr>
          <td class="font-mono text-xs">${b.bp_code}</td>
          <td class="font-medium">${b.name}</td>
          <td>${b.country}</td>
          <td class="text-xs">${b.roles}</td>
          <td>${scBadge(b.screening_status)}</td>
          <td class="text-xs font-mono">${b.denial_list || '—'}</td>
          <td class="text-xs max-w-xs truncate" title="${b.denial_reason || ''}">${b.denial_reason ? b.denial_reason.substring(0,60)+'…' : '—'}</td>
          <td class="text-center">${b.fifty_pct_rule_triggered ? '<span class="badge bg-purple-100 text-purple-800">⚖️ 該当</span>' : '—'}</td>
          <td class="text-xs font-mono">${b.ai_tm_screening_ref || '—'}</td>
          <td class="text-xs">${b.last_screened_at ? b.last_screened_at.substring(0,16) : '—'}</td>
          <td>
            ${b.screening_status !== 'CLEARED' && b.screening_status !== 'UNSCREENED' ? '' :
              `<button onclick="rescreenSingle('${b.bp_code}')"
                class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-2 py-1 rounded border border-indigo-200">
                再スクリーニング
              </button>`}
          </td>
        </tr>`).join('');
  } catch(e) { tbody.innerHTML = `<tr><td colspan="11" class="text-red-400 text-center py-4">エラー: ${e.message}</td></tr>`; }
}

async function loadScreeningLog() {
  const tbody = document.getElementById('sc-log-body');
  const statusFilter = document.getElementById('sc-log-filter').value;
  const fiftyOnly = document.getElementById('sc-fifty-only').checked;
  const params = {limit: 100};
  if (statusFilter) params.match_status = statusFilter;
  if (fiftyOnly) params.fifty_pct_only = 'true';
  try {
    const logs = await apiFetch('/gts/screening/log', params);
    const arr = Array.isArray(logs) ? logs : [];
    const statusBadge = s => {
      const map = {
        CRITICAL: 'bg-red-100 text-red-800 font-bold',
        match: 'bg-orange-100 text-orange-800',
        possible_match: 'bg-yellow-100 text-yellow-800',
        no_match: 'bg-green-100 text-green-800',
      };
      return `<span class="badge ${map[s] || 'bg-gray-100 text-gray-500'}">${s}</span>`;
    };
    tbody.innerHTML = arr.length === 0 ? '<tr><td colspan="12" class="text-center py-8 text-gray-400">ログなし</td></tr>'
      : arr.map(l => `<tr>
          <td class="text-xs">${l.id}</td>
          <td class="font-mono text-xs">${l.bp_code}</td>
          <td class="text-xs font-medium">${l.bp_name}</td>
          <td>${l.bp_country}</td>
          <td>${statusBadge(l.match_status)}</td>
          <td class="text-center">${(l.match_score*100).toFixed(0)}%</td>
          <td class="text-xs font-mono">${l.matched_list || '—'}</td>
          <td class="text-xs max-w-xs truncate" title="${l.matched_entity_name || ''}">${l.matched_entity_name || '—'}</td>
          <td class="text-center">${l.fifty_pct_rule_triggered ? '<span class="badge bg-purple-100 text-purple-800">⚖️ 該当</span>' : '—'}</td>
          <td class="text-xs">${l.parent_sanctioned_entity ? `<span class="text-orange-700">${l.parent_sanctioned_entity.substring(0,30)}</span>` : '—'}</td>
          <td class="text-xs font-mono">${l.ai_tm_screening_ref || '—'}</td>
          <td class="text-xs">${l.screened_at ? l.screened_at.substring(0,16) : '—'}</td>
        </tr>`).join('');
  } catch(e) { tbody.innerHTML = `<tr><td colspan="12" class="text-red-400 text-center py-4">エラー: ${e.message}</td></tr>`; }
}

async function rescreenAll() {
  const onlyUnscreened = document.getElementById('only-unscreened').checked;
  const btn = event.currentTarget;
  btn.disabled = true; btn.textContent = '⏳ スクリーニング中...';
  try {
    const results = await apiFetch('/gts/screening/rescreen-all', {only_unscreened: onlyUnscreened}, 'POST');
    const arr = Array.isArray(results) ? results : [];
    const blocked = arr.filter(r => r.screening_status === 'BLOCKED').length;
    const flagged = arr.filter(r => r.screening_status === 'FLAGGED').length;
    alert(`スクリーニング完了: ${arr.length}件処理\n🔴 BLOCKED: ${blocked}件\n🟠 FLAGGED: ${flagged}件\n✅ CLEARED: ${arr.length-blocked-flagged}件`);
    loadScreening();
  } catch(e) { alert('エラー: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = '🔍 スクリーニング実行'; }
}

async function rescreenSingle(bpCode) {
  try {
    const r = await apiFetch(`/gts/screening/${bpCode}/rescreen`, {}, 'POST');
    alert(`${bpCode} 再スクリーニング完了: ${r.screening_status}\nList: ${r.matched_list || 'none'}`);
    loadScreening();
  } catch(e) { alert('エラー: ' + e.message); }
}

// ── Auto-login if token exists ────────────────────────────────
(async () => {
  if (!TOKEN) return;
  try {
    const me = await apiFetch('/auth/me');
    if (me) {
      document.getElementById('loginModal').classList.add('hidden');
      document.getElementById('app').classList.remove('hidden');
      document.getElementById('userInfo').textContent = `${me.email}  |  ${me.client_id}`;
      initApp();
    }
  } catch { TOKEN = ''; sessionStorage.removeItem('erp_token'); }
})();
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return HTMLResponse(_HTML)


def get_ui_routers():
    return [router]
