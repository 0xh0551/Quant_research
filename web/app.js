/* ============================================================================
 * Quant Research — dashboard application logic
 * Talks to the FastAPI backend; all user-facing strings go through t() so the
 * UI is fully bilingual (FA/EN). Charts use Plotly for one consistent engine.
 * ========================================================================== */

const state = {
  currentSection: 'download',
  exchanges: [],
  inventory: [],
  inventoryFiltered: [],
  researchResult: null,
  activeResearchDs: null,
  activeReportTab: 'equity',
  returnType: 'simple',
  marketType: 'spot',
  sortCol: null,
  sortDir: 1,
  insightDatasets: [],
  insightDetail: null,
  edgesData: null,
  lab: { dataset: null, strategy: null, params: {} },
};

const ALL_STRATEGIES = Object.keys(STRATEGY_LABELS);

const STRATEGY_COLORS = {
  ema_trend: '#2dd4bf', rsi_mean_reversion: '#818cf8',
  bollinger_mean_reversion: '#34d399', donchian_breakout: '#fbbf24',
  atr_breakout: '#fb923c', macd_cross: '#e879f9', stochastic_mr: '#38bdf8',
  ichimoku: '#22d3ee', supertrend: '#f97316', vwap_deviation: '#60a5fa',
  cmf_trend: '#4ade80', hammer_pattern: '#facc15', engulfing: '#c084fc',
  ml_signal: '#a3e635',
};

const STRATEGY_TAG_COLORS = { Trend: '#2dd4bf', MR: '#818cf8', ML: '#34d399' };

const PLOTLY_DARK = {
  paper_bgcolor: '#161c2b',
  plot_bgcolor: '#11151f',
  font: { color: '#97a3b6', family: 'Vazirmatn,Inter,Tahoma,sans-serif', size: 12 },
};
const GRID = '#222b3d';

// ═══════════════════════════════════════════════════════════════ INIT
async function init() {
  // resolve default language: explicit user choice > install default > fa
  let lang = null;
  try { lang = localStorage.getItem('qr_lang'); } catch (e) {}
  if (!lang) {
    try {
      const r = await fetch('/api/config');
      const cfg = await r.json();
      lang = cfg.default_language;
    } catch (e) {}
  }
  setLang(lang === 'en' ? 'en' : 'fa');

  setTodayEnd();
  initResearchStrategies();
  await loadExchanges();
  await loadInventory();

  // deep-link: /…/edges opens the edges section directly
  if (/\/edges\/?$/.test(window.location.pathname)) showSection('edges');
}

function setTodayEnd() {
  document.getElementById('dl-end').value = new Date().toISOString().split('T')[0];
}

function fmtDateTime(ts) {
  return new Date(ts).toLocaleString(LANG === 'fa' ? 'fa-IR' : 'en-US');
}

// Re-render dynamic content when the language flips.
window.onLangChange = function () {
  updateSectionHeader(state.currentSection);
  initResearchStrategies();
  renderInventorySummary();
  renderInventoryCards();
  loadDownloadHistory();
  if (state.researchResult) initReport();
  if (state.insightDatasets.length) renderInsightDatasetGrid();
  if (state.insightDetail) renderDetailedInsight(state.insightDetail);
  if (state.edgesData) renderEdges(state.edgesData);
  if (state.cxData) renderCrossExchange(state.cxData);
  if (state.pfData) renderPortfolio(state.pfData);
  if (state.currentSection === 'models') loadModels();
  if (state.currentSection === 'quality') loadQuality();
};

// ═══════════════════════════════════════════════════════════════ NAVIGATION
const SECTION_KEYS = ['download','inventory','research','report','insights','lab','edges','crossex','portfolio','models','quality','logs'];

function updateSectionHeader(name) {
  document.getElementById('page-title').textContent = t('title_' + name);
  document.getElementById('page-sub').textContent = t('sub_' + name);
}

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('sec-' + name).classList.add('active');
  const nav = document.querySelector('.nav-item[data-section="' + name + '"]');
  if (nav) nav.classList.add('active');
  state.currentSection = name;
  updateSectionHeader(name);
  if (name === 'inventory') loadInventory();
  if (name === 'research') populateResearchDatasets();
  if (name === 'insights') loadInsights();
  if (name === 'lab') initLab();
  if (name === 'logs') loadLogs();
  if (name === 'edges') loadEdges();
  if (name === 'download') loadDownloadHistory();
  if (name === 'crossex') initCrossExchange();
  if (name === 'portfolio') initPortfolio();
  if (name === 'models') loadModels();
  if (name === 'quality') loadQuality();
  if (name === 'fleet') loadFleetRisk();
  if (name === 'capacity') loadCapacity();
  if (name === 'stress') loadStress();
  if (name === 'trials') loadTrials();
  if (name === 'attribution') loadAttribution();
  if (name === 'pipeline') loadPipeline();
  if (name === 'altdata') loadAltdata();
}

function refreshCurrentSection() {
  const s = state.currentSection;
  if (s === 'inventory') loadInventory();
  else if (s === 'insights') loadInsights();
  else if (s === 'research') populateResearchDatasets();
  else if (s === 'lab') initLab();
  else if (s === 'logs') loadLogs();
  else if (s === 'edges') loadEdges();
  else if (s === 'download') loadDownloadHistory();
  else if (s === 'crossex') runCrossExchange();
  else if (s === 'portfolio') initPortfolio();
  else if (s === 'models') loadModels();
  else if (s === 'quality') loadQuality();
  else if (s === 'fleet') loadFleetRisk();
  else if (s === 'capacity') loadCapacity(true);
  else if (s === 'stress') loadStress();
  else if (s === 'trials') loadTrials();
  else if (s === 'attribution') loadAttribution(true);
  else if (s === 'pipeline') loadPipeline();
  else if (s === 'altdata') loadAltdata();
}

// ═══════════════════════════════════════════════════════════════ EXCHANGES
async function loadExchanges() {
  const r = await fetch('/api/exchanges');
  const d = await r.json();
  state.exchanges = d.exchanges || [];
  const sel = document.getElementById('dl-exchange');
  sel.innerHTML = state.exchanges.map(e =>
    `<option value="${e}">${e === 'nobitex' ? '🇮🇷 Nobitex' : e}</option>`).join('');
  sel.value = 'nobitex';
  await onExchangeChange();
}

let symMode = 'select';
function setMarketType(type, btn) {
  state.marketType = type;
  document.querySelectorAll('#mt-spot,#mt-futures').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}
function toggleSymbolMode() {
  symMode = symMode === 'select' ? 'manual' : 'select';
  document.getElementById('dl-symbol-select').style.display = symMode === 'select' ? 'block' : 'none';
  document.getElementById('dl-symbol').style.display = symMode === 'manual' ? 'block' : 'none';
}
async function onExchangeChange() {
  const exch = document.getElementById('dl-exchange').value;
  if (!exch) return;
  document.getElementById('sym-loading').style.display = 'flex';
  const sel = document.getElementById('dl-symbol-select');
  sel.innerHTML = `<option value="">${t('loading')}</option>`;
  try {
    const r = await fetch(`/api/symbols/${exch}`);
    const d = await r.json();
    const syms = d.symbols || [];
    sel.innerHTML = `<option value="" data-i18n="dl_symbol_select_ph">${t('dl_symbol_select_ph')}</option>` +
      syms.map(s => `<option value="${s}">${s}</option>`).join('');
    if (exch === 'nobitex') {
      sel.value = 'BTCUSDT';
      document.getElementById('dl-symbol').value = 'BTCUSDT';
      symMode = 'select';
      sel.style.display = 'block';
      document.getElementById('dl-symbol').style.display = 'none';
    } else {
      symMode = 'manual';
      sel.style.display = 'none';
      document.getElementById('dl-symbol').style.display = 'block';
    }
  } catch (e) {
    sel.innerHTML = `<option value="">${t('error')}</option>`;
  }
  document.getElementById('sym-loading').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════════ CHECKBOX
function toggleCb(el) {
  el.classList.toggle('selected');
  el.querySelector('input').checked = el.classList.contains('selected');
}
function getCheckedValues(containerId) {
  return [...document.querySelectorAll(`#${containerId} .cb-item.selected input`)].map(i => i.value);
}

// ═══════════════════════════════════════════════════════════════ DOWNLOAD
async function startDownload() {
  const exch = document.getElementById('dl-exchange').value;
  const sym = symMode === 'select'
    ? document.getElementById('dl-symbol-select').value
    : document.getElementById('dl-symbol').value;
  const tfs = getCheckedValues('dl-timeframes');
  const start = document.getElementById('dl-start').value;
  const end = document.getElementById('dl-end').value;
  if (!exch || !sym || !tfs.length || !start) { alert(t('dl_fill_all')); return; }

  const btn = document.getElementById('dl-btn');
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> ${t('dl_downloading')}`;
  document.getElementById('dl-progress-wrap').style.display = 'block';
  try {
    const r = await fetch('/api/download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exchange: exch, symbol: sym, timeframes: tfs, start, end: end || null, market_type: state.marketType }),
    });
    const { job_id } = await r.json();
    listenToJob(job_id, 'dl', () => {
      btn.disabled = false; btn.innerHTML = downloadBtnHtml();
      loadInventory(); loadDownloadHistory();
    });
    loadDownloadHistory();
  } catch (e) {
    btn.disabled = false; btn.innerHTML = downloadBtnHtml();
    alert(t('error_colon') + e.message);
  }
}
function downloadBtnHtml() {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg> ${t('dl_start_btn')}`;
}

function listenToJob(jobId, prefix, onDone) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const d = JSON.parse(e.data);
    const pct = Math.round(d.progress || 0);
    document.getElementById(`${prefix}-bar`).style.width = pct + '%';
    document.getElementById(`${prefix}-pct`).textContent = pct + '%';
    document.getElementById(`${prefix}-msg`).textContent = jobMessage(d);
    if (d.status === 'done') {
      document.getElementById(`${prefix}-bar`).style.background = 'linear-gradient(90deg,#0d9488,#2dd4bf)';
      es.close(); if (onDone) onDone(d);
    } else if (d.status === 'error') {
      document.getElementById(`${prefix}-bar`).style.background = 'var(--red)';
      document.getElementById(`${prefix}-msg`).textContent = '❌ ' + (d.error || jobMessage(d));
      es.close(); if (onDone) onDone(d);
    }
  };
  es.onerror = () => es.close();
}

async function loadDownloadHistory() {
  const el = document.getElementById('dl-history');
  if (!el) return;
  const r = await fetch('/api/jobs');
  const { jobs } = await r.json();
  const dlJobs = (jobs || []).filter(j => j.type === 'download');
  if (!dlJobs.length) return;
  el.innerHTML = dlJobs.map(j => {
    const ico = j.status === 'done' ? '✅' : j.status === 'error' ? '❌' : '⏳';
    return `<div style="display:flex;align-items:flex-start;gap:10px;padding:10px;border-bottom:1px solid var(--border)">
      <div style="font-size:16px">${ico}</div>
      <div style="flex:1">
        <div style="font-size:12px;font-weight:600">${jobMessage(j) || j.type}</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px">${fmtDateTime(j.created_at * 1000)}</div>
      </div>
      <div style="font-size:12px;font-weight:600;color:${j.status === 'done' ? 'var(--green)' : j.status === 'error' ? 'var(--red)' : 'var(--yellow)'}">${Math.round(j.progress)}%</div>
    </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════════════ INVENTORY
async function loadInventory() {
  const r = await fetch('/api/inventory');
  const { items } = await r.json();
  state.inventory = items || [];
  state.inventoryFiltered = [...state.inventory];
  document.getElementById('inv-count').textContent = state.inventory.length;
  renderInventorySummary();
  renderInventoryCards();
  populateExchangeFilter();
}
function renderInventorySummary() {
  const items = state.inventory;
  const totalRows = items.reduce((s, i) => s + i.rows, 0);
  const totalSize = items.reduce((s, i) => s + i.size_kb, 0);
  const exchanges = new Set(items.map(i => i.exchange)).size;
  const symbols = new Set(items.map(i => i.symbol)).size;
  const cells = [
    [t('inv_metric_files'), items.length, 'var(--cyan)'],
    [t('inv_metric_candles'), fmtNum(totalRows), 'var(--green)'],
    [t('inv_metric_exchanges'), exchanges, 'var(--purple)'],
    [t('inv_metric_symbols'), symbols, 'var(--yellow)'],
    [t('inv_metric_disk'), (totalSize / 1024).toFixed(1) + ' MB', 'var(--orange)'],
  ];
  document.getElementById('inv-summary').innerHTML = cells.map(([l, v, c]) =>
    `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="color:${c}">${v}</div></div>`).join('');
}
function renderInventoryCards() {
  const el = document.getElementById('inv-cards');
  if (!el) return;
  if (!state.inventoryFiltered.length) {
    el.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:40px"><p>${t('no_data')}</p></div>`;
    return;
  }
  el.innerHTML = state.inventoryFiltered.map(item => {
    const exchColor = item.exchange === 'nobitex' ? 'var(--orange)' : item.exchange === 'binance' ? 'var(--yellow)' : 'var(--cyan)';
    return `<div class="inv-card" onclick="selectDatasetForResearch('${item.file}')">
      <div style="display:flex;align-items:flex-start;justify-content:space-between">
        <div class="exch" style="color:${exchColor}">${item.exchange.toUpperCase()}</div>
        <button class="btn btn-danger btn-sm" style="padding:4px 8px;min-width:28px"
          onclick="event.stopPropagation();deleteDataset('${item.file}',this)" title="${t('delete_file')}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
        </button>
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <div class="sym">${item.symbol}</div>
        <span class="tf-badge">${item.timeframe}</span>
        ${item.market_type && item.market_type !== 'spot' ? `<span class="tf-badge" style="background:rgba(251,146,60,.2);color:#fb923c">${item.market_type}</span>` : ''}
      </div>
      <div class="dates">📅 ${item.start} → ${item.end}</div>
      <div class="rows">📊 ${fmtNum(item.rows)} ${t('candles')} | ${item.size_kb} KB</div>
    </div>`;
  }).join('');
}
function populateExchangeFilter() {
  const exchanges = [...new Set(state.inventory.map(i => i.exchange))].sort();
  document.getElementById('inv-exch-filter').innerHTML =
    `<option value="" data-i18n="all_exchanges">${t('all_exchanges')}</option>` + exchanges.map(e => `<option value="${e}">${e}</option>`).join('');
}
function filterInventory() {
  const q = document.getElementById('inv-search').value.toLowerCase();
  const exch = document.getElementById('inv-exch-filter').value;
  state.inventoryFiltered = state.inventory.filter(i =>
    (!q || i.symbol.toLowerCase().includes(q) || i.file.toLowerCase().includes(q)) && (!exch || i.exchange === exch));
  renderInventoryCards();
}
async function deleteDataset(filename, btn) {
  if (!confirm(t('inv_confirm_delete', { file: filename }))) return;
  btn.disabled = true;
  try {
    const r = await fetch(`/api/inventory/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || t('error')); }
    await loadInventory();
    populateResearchDatasets();
  } catch (e) { alert(t('inv_delete_failed') + e.message); btn.disabled = false; }
}
function selectDatasetForResearch(file) {
  showSection('research');
  setTimeout(() => {
    document.querySelectorAll('#research-datasets .ds-item').forEach(item => {
      if (item.dataset.file === file && !item.classList.contains('selected')) item.click();
    });
  }, 150);
}

// ═══════════════════════════════════════════════════════════════ RESEARCH
function initResearchStrategies() {
  const el = document.getElementById('strategy-picker');
  if (!el) return;
  const defaultOn = new Set(['ema_trend','rsi_mean_reversion','bollinger_mean_reversion','donchian_breakout','atr_breakout','macd_cross','stochastic_mr']);
  // preserve current selection across re-render (e.g. language change)
  const prev = new Set([...el.querySelectorAll('.ds-item.selected')].map(x => x.dataset.strat));
  const hasState = el.children.length > 0;
  el.innerHTML = ALL_STRATEGIES.map(name => {
    const on = hasState ? prev.has(name) : defaultOn.has(name);
    const tag = STRATEGY_TAGS[name];
    const baseTag = tag.split(' ')[0];
    const tc = STRATEGY_TAG_COLORS[baseTag] || 'var(--cyan)';
    return `<div class="ds-item${on ? ' selected' : ''}" onclick="toggleStrategy(this)" data-strat="${name}">
      <input type="checkbox" ${on ? 'checked' : ''}/>
      <div style="font-weight:600;font-size:13px">${strategyLabel(name)}
        <span style="font-size:10px;background:${tc}26;color:${tc};padding:1px 6px;border-radius:4px;margin-inline-start:6px">${tag}</span>
      </div>
      <div style="font-size:11px;color:var(--text3);margin-top:3px">${strategyDesc(name)}</div>
    </div>`;
  }).join('');
}
function populateResearchDatasets() {
  const el = document.getElementById('research-datasets');
  if (!el) return;
  if (!state.inventory.length) {
    el.innerHTML = `<div class="empty-state" style="padding:24px"><p>${t('no_data')}</p></div>`;
    updateDsCount(); return;
  }
  el.innerHTML = state.inventory.map(item => {
    const exchColor = item.exchange === 'nobitex' ? '#fb923c' : item.exchange === 'binance' ? '#fbbf24' : '#2dd4bf';
    return `<div class="ds-item" onclick="toggleResearchDataset(this)"
      data-exchange="${item.exchange}" data-symbol="${item.symbol}" data-tf="${item.timeframe}" data-file="${item.file}">
      <input type="checkbox"/>
      <div style="font-weight:600;font-size:13px">${item.symbol}
        <span style="font-size:10px;padding:1px 6px;border-radius:4px;background:${exchColor}22;color:${exchColor};margin-inline-start:6px">${item.exchange.toUpperCase()}</span>
        <span class="tf-badge">${item.timeframe}</span>
      </div>
      <div style="font-size:11px;color:var(--text3);margin-top:3px">${item.start} → ${item.end} &nbsp;·&nbsp; ${fmtNum(item.rows)} ${t('candles')}</div>
    </div>`;
  }).join('');
  updateDsCount();
}
function toggleResearchDataset(el) { el.classList.toggle('selected'); el.querySelector('input').checked = el.classList.contains('selected'); updateDsCount(); }
function updateDsCount() {
  const n = document.querySelectorAll('#research-datasets .ds-item.selected').length;
  document.getElementById('ds-selected-count').textContent = t('res_selected_count', { n });
}
function toggleStrategy(el) { el.classList.toggle('selected'); el.querySelector('input').checked = el.classList.contains('selected'); }
function setReturnType(type, btn) {
  state.returnType = type;
  btn.parentElement.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}
async function startResearch() {
  const selectedDs = [...document.querySelectorAll('#research-datasets .ds-item.selected')].map(el => ({
    file: el.dataset.file, exchange: el.dataset.exchange, symbol: el.dataset.symbol, timeframe: el.dataset.tf,
  }));
  const selectedStrats = [...document.querySelectorAll('#strategy-picker .ds-item.selected')].map(el => el.dataset.strat);
  if (!selectedDs.length) { alert(t('res_need_dataset')); return; }
  if (!selectedStrats.length) { alert(t('res_need_strategy')); return; }

  const btn = document.getElementById('res-btn');
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> ${t('res_running')}`;
  document.getElementById('res-progress-wrap').style.display = 'block';
  document.getElementById('res-bar').style.width = '0%';
  document.getElementById('res-bar').style.background = 'var(--grad-accent)';

  const payload = {
    datasets: selectedDs, strategies: selectedStrats,
    start: document.getElementById('res-start').value || null,
    end: document.getElementById('res-end').value || null,
    return_type: state.returnType,
    initial_capital: parseFloat(document.getElementById('res-capital').value) || 10000,
    fee_bps: parseFloat(document.getElementById('res-fee').value) || 10,
    slippage_bps: parseFloat(document.getElementById('res-slippage').value) || 2,
    execution_style: state.executionStyle || 'taker',
    use_real_funding: document.getElementById('res-real-funding').checked,
  };
  try {
    const r = await fetch('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const { job_id } = await r.json();
    listenToJob(job_id, 'res', async (jobData) => {
      btn.disabled = false; btn.innerHTML = researchBtnHtml();
      if (jobData.status === 'done') {
        const res = await fetch(`/api/jobs/${job_id}/result`);
        state.researchResult = await res.json();
        showSection('report');
        setTimeout(initReport, 60);
      }
    });
  } catch (e) {
    btn.disabled = false; btn.innerHTML = researchBtnHtml();
    alert(t('error_colon') + e.message);
  }
}
function researchBtnHtml() {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg> ${t('res_run_btn')}`;
}

// ═══════════════════════════════════════════════════════════════ REPORT
function initReport() {
  if (!state.researchResult || !state.researchResult.datasets) return;
  const datasets = state.researchResult.datasets;
  document.getElementById('report-empty').style.display = 'none';
  document.getElementById('report-content').style.display = 'block';
  document.getElementById('report-ds-tabs').innerHTML = datasets.map((ds, i) =>
    `<button class="btn ${i === 0 ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="selectReportDataset(${i}, this)" data-idx="${i}">
      ${ds.symbol} <span style="opacity:.7">${ds.exchange}</span> ${ds.timeframe}</button>`).join('');
  state.activeResearchDs = datasets[0];
  buildMonthlyStratSelect();
  renderEquityChart();
  renderMetricsTable();
  renderDistributionChart();
}
function selectReportDataset(idx, btn) {
  document.querySelectorAll('#report-ds-tabs button').forEach(b => { b.classList.remove('btn-primary'); b.classList.add('btn-secondary'); });
  btn.classList.add('btn-primary'); btn.classList.remove('btn-secondary');
  state.activeResearchDs = state.researchResult.datasets[idx];
  buildMonthlyStratSelect();
  renderEquityChart(); renderDrawdownChart(); renderMonthlyChart(); renderRollingChart(); renderDistributionChart(); renderMetricsTable();
}
function buildMonthlyStratSelect() {
  const ds = state.activeResearchDs; if (!ds) return;
  const opts = '<option value="buy_hold">Buy & Hold</option>' +
    (ds.strategies || []).filter(s => !s.error).map(s => `<option value="${s.name}">${strategyLabel(s.name)}</option>`).join('');
  document.getElementById('monthly-strat-select').innerHTML = opts;
  document.getElementById('dist-strat-select').innerHTML = opts;
}
function switchReportTab(name, el) {
  document.querySelectorAll('.report-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.report-tab-content').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('rtab-' + name).classList.add('active');
  state.activeReportTab = name;
  ({ equity: renderEquityChart, drawdown: renderDrawdownChart, monthly: renderMonthlyChart, rolling: renderRollingChart, distribution: renderDistributionChart, metrics: renderMetricsTable }[name] || (() => {}))();
}
function renderEquityChart() {
  const ds = state.activeResearchDs; if (!ds) return;
  const showRegime = document.getElementById('show-regime').checked;
  const ts = ds.timestamps || [];
  const traces = [{ x: ts, y: ds.buy_hold_equity || [], mode: 'lines', name: 'Buy & Hold', line: { color: '#94a3b8', width: 1.5, dash: 'dot' }, hovertemplate: '<b>Buy&Hold</b><br>%{x}<br>$%{y:.2f}<extra></extra>' }];
  (ds.strategies || []).filter(s => !s.error).forEach(strat => {
    traces.push({ x: ts, y: strat.equity, mode: 'lines', name: strategyLabel(strat.name), line: { color: STRATEGY_COLORS[strat.name] || '#fff', width: 2 }, hovertemplate: `<b>${strategyLabel(strat.name)}</b><br>%{x}<br>$%{y:.2f}<extra></extra>` });
  });
  const shapes = [];
  if (showRegime && ds.regime_bands) ds.regime_bands.forEach(b => shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: b.start, x1: b.end, y0: 0, y1: 1, fillcolor: b.regime === 'up' ? 'rgba(52,211,153,.06)' : 'rgba(248,113,113,.06)', line: { width: 0 }, layer: 'below' }));
  Plotly.react('chart-equity', traces, { ...PLOTLY_DARK, shapes, xaxis: { gridcolor: GRID, zeroline: false }, yaxis: { gridcolor: GRID, zeroline: false, title: t('rep_portfolio_value') }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID, borderwidth: 1, x: 0, y: 1 }, hovermode: 'x unified', margin: { l: 60, r: 20, t: 20, b: 50 } }, { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });
}
function renderDrawdownChart() {
  const ds = state.activeResearchDs; if (!ds) return;
  const ts = ds.timestamps || [];
  const traces = [];
  (ds.strategies || []).filter(s => !s.error).forEach(strat => {
    traces.push({ x: ts, y: (strat.drawdown || []).map(v => v * 100), fill: 'tozeroy', mode: 'lines', name: strategyLabel(strat.name), line: { color: STRATEGY_COLORS[strat.name], width: 1.5 }, hovertemplate: `<b>${strategyLabel(strat.name)}</b><br>%{x}<br>%{y:.2f}%<extra></extra>` });
  });
  Plotly.react('chart-drawdown', traces, { ...PLOTLY_DARK, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, title: 'Drawdown %', ticksuffix: '%' }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID, borderwidth: 1 }, hovermode: 'x unified', margin: { l: 60, r: 20, t: 20, b: 50 } }, { responsive: true });
}
function renderMonthlyChart() {
  const ds = state.activeResearchDs; if (!ds || !ds.monthly_returns) return;
  const monthly = ds.monthly_returns;
  if (!monthly.length) { document.getElementById('chart-monthly').innerHTML = `<div class="empty-state"><p>${t('insufficient_data')}</p></div>`; return; }
  const years = [...new Set(monthly.map(m => m.year))].sort();
  const ms = months();
  const z = years.map(y => ms.map((_, mi) => { const rec = monthly.find(m => m.year === y && m.month === mi + 1); return rec ? parseFloat((rec.return * 100).toFixed(2)) : null; }));
  Plotly.react('chart-monthly', [{ z, x: ms, y: years.map(String), type: 'heatmap', colorscale: [[0, '#7f1d1d'], [0.35, '#f87171'], [0.5, '#222b3d'], [0.65, '#34d399'], [1, '#065f46']], zmid: 0, text: z.map(row => row.map(v => v !== null ? v.toFixed(1) + '%' : '')), texttemplate: '%{text}', textfont: { size: 10 }, hovertemplate: '%{y} %{x}<br>%{z:.2f}%<extra></extra>', colorbar: { title: '%', ticksuffix: '%' } }], { ...PLOTLY_DARK, margin: { l: 60, r: 60, t: 20, b: 60 }, xaxis: { side: 'bottom' } }, { responsive: true });
}
function renderRollingChart() {
  const ds = state.activeResearchDs; if (!ds) return;
  const ts = ds.timestamps || []; const win = 30; const traces = [];
  (ds.strategies || []).filter(s => !s.error).forEach(strat => {
    const eq = strat.equity || [];
    const returns = eq.map((v, i) => i === 0 ? 0 : (v - eq[i - 1]) / eq[i - 1]);
    const rolling = returns.map((_, i) => { if (i < win) return null; const slice = returns.slice(i - win, i); const mean = slice.reduce((a, b) => a + b, 0) / win; const std = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / win); return std > 0 ? mean / std * Math.sqrt(365) : 0; });
    traces.push({ x: ts, y: rolling, mode: 'lines', name: strategyLabel(strat.name), line: { color: STRATEGY_COLORS[strat.name], width: 1.5 }, hovertemplate: `<b>${strategyLabel(strat.name)}</b><br>%{x}<br>Sharpe: %{y:.2f}<extra></extra>` });
  });
  traces.push({ x: [ts[0], ts[ts.length - 1]], y: [0, 0], mode: 'lines', name: t('zero'), showlegend: false, line: { color: '#f87171', width: 1, dash: 'dash' } });
  Plotly.react('chart-rolling', traces, { ...PLOTLY_DARK, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, title: 'Rolling Sharpe (30)' }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID, borderwidth: 1 }, hovermode: 'x unified', margin: { l: 60, r: 20, t: 20, b: 50 } }, { responsive: true });
}
function renderDistributionChart() {
  const ds = state.activeResearchDs; if (!ds) return;
  const stratName = document.getElementById('dist-strat-select').value;
  let distData = null, label = 'Buy & Hold', color = '#94a3b8';
  if (stratName === 'buy_hold') distData = ds.return_distribution;
  else { const s = (ds.strategies || []).find(x => x.name === stratName); if (s && s.return_dist) { distData = s.return_dist; label = strategyLabel(s.name); color = STRATEGY_COLORS[s.name] || '#fff'; } }
  if (!distData || !distData.x) { document.getElementById('chart-distribution').innerHTML = `<div class="empty-state"><p>${t('insufficient_data')}</p></div>`; document.getElementById('dist-stats-grid').innerHTML = ''; return; }
  const { x, y, mean, std, skew, kurt } = distData;
  const maxY = Math.max(...y);
  const normpdf = x.map(xi => maxY * Math.exp(-0.5 * ((xi - mean) / std) ** 2));
  Plotly.react('chart-distribution', [
    { x, y, type: 'bar', name: t('rep_count'), marker: { color: color + '55', line: { color, width: 1 } }, hovertemplate: `%{x:.2f}%<br>%{y} ${t('rep_count_times')}<extra></extra>` },
    { x, y: normpdf, type: 'scatter', mode: 'lines', name: t('normal_dist'), line: { color: '#fbbf24', width: 2, dash: 'dot' }, hovertemplate: '%{x:.2f}%<extra></extra>' },
    { x: [mean, mean], y: [0, maxY * 1.05], type: 'scatter', mode: 'lines', name: t('average'), line: { color: '#34d399', width: 1.5, dash: 'dash' } },
  ], { ...PLOTLY_DARK, xaxis: { gridcolor: GRID, title: '%', ticksuffix: '%' }, yaxis: { gridcolor: GRID, title: t('rep_count') }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID, borderwidth: 1 }, margin: { l: 60, r: 20, t: 20, b: 60 }, bargap: 0.05 }, { responsive: true });
  document.getElementById('dist-stats-grid').innerHTML = [
    [t('stat_mean'), mean.toFixed(3) + '%', mean >= 0 ? 'var(--green)' : 'var(--red)'],
    [t('stat_std'), std.toFixed(3) + '%', 'var(--yellow)'],
    [t('stat_skew'), typeof skew === 'number' ? skew.toFixed(3) : '-', 'var(--text)'],
    [t('stat_kurt'), typeof kurt === 'number' ? kurt.toFixed(3) : '-', 'var(--text)'],
  ].map(([l, v, c]) => `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${c}">${v}</div></div>`).join('');
}
function renderMetricsTable() {
  const ds = state.activeResearchDs; if (!ds) return;
  const strats = (ds.strategies || []).filter(s => !s.error); if (!strats.length) return;
  const METRICS = [
    { key: 'total_return', label: t('m_total_return'), fmt: pct, higher: true },
    { key: 'cagr', label: t('m_cagr'), fmt: pct, higher: true },
    { key: 'sharpe', label: t('m_sharpe'), fmt: n2, higher: true },
    { key: 'sortino', label: t('m_sortino'), fmt: n2, higher: true },
    { key: 'calmar', label: t('m_calmar'), fmt: n2, higher: true },
    { key: 'max_drawdown', label: t('m_max_dd'), fmt: pct, higher: false },
    { key: 'profit_factor', label: t('m_profit_factor'), fmt: n2, higher: true },
    { key: 'win_rate', label: t('m_win_rate'), fmt: pct, higher: true },
  ];
  // execution-sim metrics appear only when the maker/realistic engine ran
  if (strats.some(s => s.metrics.exec_fill_ratio !== undefined)) {
    METRICS.push(
      { key: 'exec_fill_ratio', label: t('m_exec_fill_ratio'), fmt: pct, higher: true },
      { key: 'exec_maker_fill_rate', label: t('m_exec_maker_rate'), fmt: pct, higher: true },
      { key: 'exec_fallback_rate', label: t('m_exec_fallback'), fmt: pct, higher: false },
      { key: 'exec_missed_rate', label: t('m_exec_missed'), fmt: pct, higher: false },
      { key: 'exec_effective_cost_bps', label: t('m_exec_cost'), fmt: n2, higher: false },
    );
  }
  const bhMetrics = ds.buy_hold_metrics || {};
  const rows = METRICS.map(m => { const vals = strats.map(s => s.metrics[m.key]); return { m, vals, bhVal: bhMetrics[m.key], best: m.higher ? Math.max(...vals) : Math.min(...vals), worst: m.higher ? Math.min(...vals) : Math.max(...vals) }; });
  document.getElementById('metrics-table-wrap').innerHTML = `<table>
    <thead><tr><th>${t('rep_metric')}</th><th style="color:#94a3b8">Buy & Hold</th>
      ${strats.map(s => `<th style="color:${STRATEGY_COLORS[s.name] || '#fff'}">${strategyLabel(s.name)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(({ m, vals, bhVal, best, worst }) => `<tr>
        <td style="font-weight:600;color:var(--text2)">${m.label}</td>
        <td>${bhVal !== undefined ? m.fmt(bhVal) : '-'}</td>
        ${vals.map(v => { const isBest = Math.abs(v - best) < 0.0001; const isWorst = Math.abs(v - worst) < 0.0001 && strats.length > 1; return `<td class="${isBest ? 'cell-green' : isWorst ? 'cell-red' : ''}">${m.fmt(v)}</td>`; }).join('')}
      </tr>`).join('')}
      ${strats.some(s => s.sharpe_ci) ? `<tr><td style="font-weight:600;color:var(--text2)">${t('rep_ci_sharpe')}</td><td class="muted">—</td>${strats.map(s => `<td class="muted" style="font-size:11px">${s.sharpe_ci ? s.sharpe_ci.low.toFixed(1) + '–' + s.sharpe_ci.high.toFixed(1) : '—'}</td>`).join('')}</tr>` : ''}</tbody></table>`;
}
function exportMetricsCsv() {
  const ds = state.activeResearchDs; if (!ds) return;
  const KEYS = ['total_return', 'cagr', 'sharpe', 'sortino', 'calmar', 'max_drawdown', 'profit_factor', 'win_rate'];
  const strats = (ds.strategies || []).filter(s => !s.error);
  const header = ['metric', 'buy_hold', ...strats.map(s => s.name)].join(',');
  const rows = KEYS.map(k => [k, ds.buy_hold_metrics[k] || 0, ...strats.map(s => s.metrics[k] || 0)].join(','));
  downloadFile([header, ...rows].join('\n'), `metrics_${ds.dataset_id}.csv`, 'text/csv');
}
function downloadChartPng(id) { Plotly.downloadImage(id, { format: 'png', width: 1400, height: 700, filename: `chart_${id}` }); }

// ═══════════════════════════════════════════════════════════════ INSIGHTS
async function loadInsights() {
  const grid = document.getElementById('insights-dataset-grid');
  grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;padding:40px"><span class="spinner" style="width:28px;height:28px"></span></div>';
  try {
    const r = await fetch('/api/insights'); const d = await r.json();
    state.insightDatasets = d.datasets || [];
    renderInsightDatasetGrid();
  } catch (e) { grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><p>${t('error_colon')}${e.message}</p></div>`; }
}
function renderInsightDatasetGrid() {
  const grid = document.getElementById('insights-dataset-grid');
  const items = state.insightDatasets;
  if (!items.length) { grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:40px"><p>${t('no_data')}</p><small>${t('ins_no_data_hint')}</small></div>`; return; }
  grid.innerHTML = items.map(item => {
    const exchColor = item.exchange === 'nobitex' ? 'var(--orange)' : item.exchange === 'binance' ? 'var(--yellow)' : 'var(--cyan)';
    return `<div class="inv-card" onclick="loadDetailedInsight('${item.file}','${item.symbol}','${item.exchange}','${item.timeframe}')">
      <div class="exch" style="color:${exchColor}">${item.exchange.toUpperCase()}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><div class="sym">${item.symbol}</div><span class="tf-badge">${item.timeframe}</span></div>
      <div class="dates">📅 ${item.start} → ${item.end}</div>
      <div class="rows">📊 ${fmtNum(item.rows)} ${t('candles')}</div>
      <div style="margin-top:10px;font-size:12px;color:var(--cyan);text-align:center">${t('ins_click_to_analyze')}</div>
    </div>`;
  }).join('');
}
function backToInsightsList() {
  document.getElementById('insights-step1').style.display = '';
  document.getElementById('insights-step2').style.display = 'none';
  state.insightDetail = null;
}
function reRunInsight() {
  const a = state.insightArgs;
  if (a) loadDetailedInsight(a.file, a.symbol, a.exchange, a.tf);
}
async function loadDetailedInsight(file, symbol, exchange, tf) {
  state.insightArgs = { file, symbol, exchange, tf };
  document.getElementById('insights-step1').style.display = 'none';
  document.getElementById('insights-step2').style.display = '';
  document.getElementById('ins-det-title').textContent = `${symbol} · ${exchange.toUpperCase()} · ${tf}`;
  document.getElementById('insights-detail-loading').style.display = 'block';
  document.getElementById('insights-detail-content').style.display = 'none';
  try {
    const r = await fetch('/api/insights/detailed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file, ...qrDateRange('ins') }) });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || r.statusText); }
    state.insightDetail = await r.json();
    renderDetailedInsight(state.insightDetail);
  } catch (e) {
    document.getElementById('insights-detail-content').innerHTML = `<div class="empty-state"><p>${t('error_colon')}${e.message}</p></div>`;
    document.getElementById('insights-detail-content').style.display = 'block';
  }
  document.getElementById('insights-detail-loading').style.display = 'none';
}
function renderDetailedInsight(d) {
  const rec = d.recommendation || {};
  const stratColor = STRATEGY_COLORS[rec.strategy] || 'var(--cyan)';
  const conf = rec.confidence || 0;
  const confColor = conf >= 70 ? 'var(--green)' : conf >= 40 ? 'var(--yellow)' : 'var(--red)';
  const confLabel = conf >= 70 ? t('conf_high') : conf >= 40 ? t('conf_medium') : t('conf_low');
  const momSign = d.momentum > 0 ? '+' : '';
  const momColor = d.momentum > 2 ? 'var(--green)' : d.momentum < -2 ? 'var(--red)' : 'var(--yellow)';
  const reasons = (rec.reasons || []).map(recReason).filter(Boolean);

  let futuresToast = '';
  if (d.allow_short) futuresToast = `<div style="font-size:12px;padding:8px 16px;background:rgba(248,113,113,.1);border-bottom:1px solid rgba(248,113,113,.2);color:#fca5a5">⚡ <strong>Futures:</strong> ${t('ins_futures_mode')}</div>`;

  document.getElementById('ins-recommendation-main').innerHTML = futuresToast + `
    <div style="padding:24px;background:linear-gradient(135deg,${stratColor}14,${stratColor}05,var(--bg3))">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text3);margin-bottom:12px">${t('ins_rec_for_next')}</div>
      <div style="display:flex;flex-wrap:wrap;align-items:flex-start;gap:24px">
        <div>
          <div style="font-size:34px;font-weight:800;color:${stratColor};line-height:1">${strategyLabel(rec.strategy)}</div>
          <div style="font-size:12px;color:var(--text3);margin-top:4px">${t('ins_recent_sharpe')}: <b style="color:${stratColor}">${rec.sharpe_score}</b></div>
        </div>
        <div style="min-width:160px">
          <div style="font-size:12px;color:var(--text3);margin-bottom:6px">${t('ins_confidence')}</div>
          <div style="display:flex;align-items:center;gap:10px">
            <div style="flex:1;height:10px;background:var(--bg4);border-radius:5px;overflow:hidden"><div style="width:${conf}%;height:100%;background:${confColor};border-radius:5px;transition:width .6s"></div></div>
            <span style="font-size:18px;font-weight:700;color:${confColor}">${conf}%</span>
          </div>
          <div style="font-size:11px;color:${confColor};margin-top:4px">${confLabel}</div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
          <span style="font-size:12px;padding:4px 12px;border-radius:20px;background:var(--bg4);color:var(--text2)">${t('ins_regime')}: <b style="color:${rec.regime_fit ? 'var(--green)' : 'var(--yellow)'}">${regimeLabel(rec.regime)}</b></span>
          <span style="font-size:12px;padding:4px 12px;border-radius:20px;background:var(--bg4);color:var(--text2)">${t('ins_momentum')}: <b style="color:${momColor}">${momSign}${(d.momentum || 0).toFixed(1)}%</b></span>
        </div>
      </div>
      <div style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px">
        ${reasons.map(r => `<span style="font-size:12px;padding:4px 12px;border-radius:6px;background:rgba(255,255,255,.04);color:var(--text2);border:1px solid var(--border)">• ${r}</span>`).join('')}
      </div>
      ${rec.alt_strategy ? `<div style="margin-top:14px;padding:10px 14px;background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.2);border-radius:8px;font-size:12px;color:var(--yellow)">⚠ ${t('ins_alt_strategy')}<b>${strategyLabel(rec.alt_strategy)}</b></div>` : ''}
    </div>`;

  const bh = d.buy_hold_metrics || {}, oracle = d.oracle_metrics || {}, wf = d.wf_metrics || {};
  document.getElementById('ins-metrics-grid').innerHTML = [
    [t('ins_m_wf_sharpe'), wf.sharpe, 'var(--purple)'],
    [t('ins_m_wf_cagr'), wf.cagr, 'var(--purple)', true],
    [t('ins_m_wf_dd'), wf.max_drawdown, '#a78bfa', true],
    [t('ins_m_bh_sharpe'), bh.sharpe, '#94a3b8'],
    [t('ins_m_oracle_sharpe'), oracle.sharpe, 'var(--cyan)'],
  ].map(([l, v, c, isPct]) => { if (v == null) return ''; const fmt = isPct ? (v * 100).toFixed(1) + '%' : v.toFixed(2); return `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${c}">${fmt}</div></div>`; }).join('');

  const ts = d.timestamps || [];
  const traces = [
    { x: ts, y: d.buy_hold_equity, mode: 'lines', name: `Buy & Hold (${t('benchmark')})`, line: { color: '#94a3b8', width: 1.5, dash: 'dot' } },
    { x: ts, y: d.wf_equity, mode: 'lines', name: t('ins_daily_decision'), line: { color: '#818cf8', width: 2.5 } },
    { x: ts, y: d.oracle_equity, mode: 'lines', name: t('ins_oracle_ceiling'), line: { color: '#2dd4bf', width: 1.5, dash: 'dot' } },
  ];
  Object.entries(d.strategy_equities || {}).forEach(([strat, eq]) => traces.push({ x: ts, y: eq, mode: 'lines', name: strategyLabel(strat), line: { color: STRATEGY_COLORS[strat] || '#fff', width: 1 }, visible: 'legendonly' }));
  Plotly.react('chart-ins-equity', traces, { ...PLOTLY_DARK, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, title: t('ins_value') }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID, borderwidth: 1 }, hovermode: 'x unified', margin: { l: 60, r: 20, t: 20, b: 50 } }, { responsive: true });

  const scores = d.recent_scores || {};
  const vals = Object.values(scores).filter(isFinite);
  const maxS = Math.max(...vals, 0.01), minS = Math.min(...vals, 0), range = maxS - minS || 1;
  document.getElementById('ins-sharpe-bars').innerHTML = Object.entries(scores).sort((a, b) => b[1] - a[1]).map(([strat, score]) => {
    const isBest = strat === d.best_now; const c = STRATEGY_COLORS[strat] || '#94a3b8'; const w = Math.max(3, Math.round((score - minS) / range * 100));
    return `<div class="score-bar-row"><div class="score-bar-label" style="${isBest ? 'color:' + c + ';font-weight:700' : ''}">${strategyLabel(strat)}</div>
      <div class="score-bar-bg"><div class="score-bar-fill" style="width:${w}%;background:${isBest ? c : '#2f3b57'}"></div></div>
      <div class="score-bar-val" style="color:${score > 0 ? 'var(--green)' : score < 0 ? 'var(--red)' : 'var(--text3)'}">${score.toFixed(2)}</div></div>`;
  }).join('');

  const wins = d.strategy_windows || [];
  const tlEl = document.getElementById('ins-windows-timeline');
  if (wins.length) {
    const stratSet = [...new Set(wins.map(w => w.best_strategy))];
    tlEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
        ${stratSet.map(s => `<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${(STRATEGY_COLORS[s] || '#94a3b8')}20;color:${STRATEGY_COLORS[s] || '#94a3b8'};font-weight:600">${strategyLabel(s)}</span>`).join('')}</div>
      <div style="display:flex;gap:2px;height:32px;border-radius:6px;overflow:hidden;margin-bottom:6px">
        ${wins.map(w => { const c = STRATEGY_COLORS[w.best_strategy] || '#94a3b8'; return `<div title="${strategyLabel(w.best_strategy)} | ${w.start}→${w.end} | Sharpe:${w.best_sharpe}" style="flex:1;background:${c}40;border-inline-start:2px solid ${c};min-width:3px" onmouseover="this.style.opacity='.6'" onmouseout="this.style.opacity='1'"></div>`; }).join('')}</div>
      <div style="font-size:11px;color:var(--text3)">${t('ins_rotation_legend')}</div>`;
  } else tlEl.innerHTML = `<p style="font-size:12px;color:var(--text3);padding:10px 0">${t('insufficient_data')}</p>`;

  renderStrategyRotationOnPrice(d);
  renderMLRLFitness(d.ml_rl_fitness);
  document.getElementById('insights-detail-content').style.display = 'block';
}
function renderStrategyRotationOnPrice(d) {
  const ts = d.timestamps || [], price = d.price || [], wins = d.strategy_windows || [];
  const traces = [{ x: ts, y: price, mode: 'lines', name: 'Price', line: { color: '#94a3b8', width: 1.5 }, hovertemplate: '%{x}<br>$%{y:.4f}<extra>Price</extra>' }];
  const shapes = wins.map(w => ({ type: 'rect', xref: 'x', yref: 'paper', x0: w.start, x1: w.end, y0: 0, y1: 1, fillcolor: (STRATEGY_COLORS[w.best_strategy] || '#94a3b8') + '1a', line: { width: 1, color: (STRATEGY_COLORS[w.best_strategy] || '#94a3b8') + '40' }, layer: 'below' }));
  [...new Set(wins.map(w => w.best_strategy))].forEach(strat => traces.push({ x: [null], y: [null], mode: 'markers', marker: { color: STRATEGY_COLORS[strat] || '#94a3b8', size: 10, symbol: 'square' }, name: strategyLabel(strat), showlegend: true }));
  Plotly.react('chart-ins-strategy-price', traces, { ...PLOTLY_DARK, shapes, xaxis: { gridcolor: GRID, zeroline: false }, yaxis: { gridcolor: GRID, zeroline: false, title: 'Price' }, legend: { bgcolor: 'rgba(0,0,0,.5)', bordercolor: GRID, borderwidth: 1, x: 0, y: 1 }, hovermode: 'x unified', margin: { l: 60, r: 20, t: 20, b: 50 } }, { responsive: true });
}
function renderMLRLFitness(fit) {
  if (!fit) return;
  document.getElementById('ins-ml-score').textContent = fit.ml_score || 0;
  document.getElementById('ins-rl-score').textContent = fit.rl_score || 0;
  document.getElementById('ins-ml-bar').style.width = (fit.ml_score || 0) + '%';
  document.getElementById('ins-rl-bar').style.width = (fit.rl_score || 0) + '%';
  const det = fit.details || {};
  const fmtv = v => v !== undefined && v !== null ? (typeof v === 'number' && Math.abs(v) > 100 ? v : Number(v).toFixed(3)) : '—';
  const mlRows = [[t('d_autocorr'), det.autocorrelation], [t('d_hurst'), det.hurst], [t('d_ic'), det.ic], [t('d_stationarity'), det.stationarity], [t('d_sample'), det.sample_count]];
  const rlRows = [[t('d_regime_changes'), det.regime_changes], [t('d_regime_diversity'), det.regime_diversity], [t('d_reward_density'), det.reward_density], [t('d_vol_cluster'), det.vol_clustering], [t('d_kurtosis'), det.kurtosis]];
  document.getElementById('ins-ml-detail').innerHTML = mlRows.map(([l, v]) => `<div class="fitness-detail-row"><span>${l}</span><span style="color:var(--cyan);font-weight:600">${fmtv(v)}</span></div>`).join('');
  document.getElementById('ins-rl-detail').innerHTML = rlRows.map(([l, v]) => `<div class="fitness-detail-row"><span>${l}</span><span style="color:#a78bfa;font-weight:600">${fmtv(v)}</span></div>`).join('');
  const banner = document.getElementById('ins-ml-rl-banner');
  if (fit.recommendation) {
    const colors = { ml: 'var(--cyan)', rl: '#a78bfa', both: 'var(--yellow)' };
    const icons = { ml: '🤖', rl: '🎮', both: '⚖️' };
    const c = colors[fit.recommendation] || 'var(--cyan)';
    const { hint, bot } = mlrlHint(fit);
    banner.style.display = 'block';
    banner.innerHTML = `<div style="padding:14px 18px;background:${c}0d;border:1px solid ${c}33;border-radius:10px">
      <div style="font-size:14px;font-weight:700;color:${c};margin-bottom:6px">${icons[fit.recommendation] || ''} ${hint}</div>
      <div style="font-size:12px;color:var(--text2)">${bot}</div></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════ FORMATTERS
function pct(v) { if (v == null) return '-'; return `<span style="color:${v >= 0 ? 'var(--green)' : 'var(--red)'}">${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%</span>`; }
function n2(v) { return v == null ? '-' : v.toFixed(2); }
function fmtNum(n) { return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : String(n); }
function downloadFile(content, name, mime) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([content], { type: mime })); a.download = name; a.click(); }
const fmtPct = x => (x == null ? '—' : (x >= 0 ? '+' : '') + (x * 100).toFixed(1) + '%');
const fmtN = (x, d = 2) => (x == null ? '—' : Number(x).toFixed(d));
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// ═══════════════════════════════════════════════════════════════ LOGS
const LOG_COLORS = { DEBUG: '#64748b', INFO: '#34d399', WARNING: '#fbbf24', ERROR: '#f87171', CRITICAL: '#e879f9' };
async function loadLogs() {
  const level = document.getElementById('log-level-filter').value;
  const file = document.getElementById('log-file-filter').value;
  const n = parseInt(document.getElementById('log-lines').value) || 200;
  const el = document.getElementById('log-lines-container');
  el.innerHTML = `<span style="color:var(--text3)">${t('loading')}</span>`;
  try {
    const url = file === 'errors' ? `/api/logs/errors?n=${n}` : `/api/logs?n=${n}&level=${level}`;
    const r = await fetch(url); const { lines, total } = await r.json();
    renderLogLines(lines, total);
  } catch (e) { el.innerHTML = `<span style="color:var(--red)">${t('error_colon')}${e.message}</span>`; }
}
function renderLogLines(lines) {
  const el = document.getElementById('log-lines-container');
  if (!lines.length) { el.innerHTML = `<span style="color:var(--text3)">${t('logs_none')}</span>`; updateLogStats(lines); return; }
  el.innerHTML = lines.map(line => {
    let color = 'var(--text2)', bg = '';
    for (const [lvl, c] of Object.entries(LOG_COLORS)) { if (line.includes(`  ${lvl}  `) || line.includes(`  ${lvl} `)) { color = c; if (lvl === 'ERROR' || lvl === 'CRITICAL') bg = `background:${c}10;`; break; } }
    return `<div style="color:${color};${bg}padding:1px 4px;border-radius:3px;white-space:pre-wrap;word-break:break-all">${esc(line)}</div>`;
  }).join('');
  updateLogStats(lines);
  if (document.getElementById('log-autoscroll').checked) el.scrollTop = el.scrollHeight;
}
function updateLogStats(lines) {
  const counts = { INFO: 0, WARNING: 0, ERROR: 0, CRITICAL: 0 };
  lines.forEach(l => { for (const lvl of Object.keys(counts)) { if (l.includes(`  ${lvl}  `) || l.includes(`  ${lvl} `)) { counts[lvl]++; break; } } });
  document.getElementById('logs-stats').innerHTML = [
    [t('logs_stat_lines'), lines.length, 'var(--cyan)'], ['INFO', counts.INFO, 'var(--green)'],
    ['WARNING', counts.WARNING, 'var(--yellow)'], ['ERROR', counts.ERROR + counts.CRITICAL, 'var(--red)'],
  ].map(([l, v, c]) => `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${c}">${v}</div></div>`).join('');
}

// ═══════════════════════════════════════════════════════════════ LAB
function initLab() {
  document.getElementById('lab-dataset-select').innerHTML = `<option value="" data-i18n="lab_dataset_ph">${t('lab_dataset_ph')}</option>` +
    state.inventory.map(item => { const isF = item.market_type && item.market_type !== 'spot'; return `<option value="${item.file}" data-futures="${isF}">${item.symbol} (${item.exchange} · ${item.timeframe}${isF ? ' · FUTURES' : ''})</option>`; }).join('');
  document.getElementById('lab-strategy-select').innerHTML = `<option value="" data-i18n="lab_strategy_ph">${t('lab_strategy_ph')}</option>` +
    ALL_STRATEGIES.map(k => `<option value="${k}">${strategyLabel(k)}</option>`).join('');
}
function onLabDatasetChange() {
  const sel = document.getElementById('lab-dataset-select');
  const isF = sel.options[sel.selectedIndex] && sel.options[sel.selectedIndex].dataset.futures === 'true';
  state.lab.dataset = sel.value;
  document.getElementById('lab-futures-notice').style.display = isF ? 'block' : 'none';
  updateLabButtons();
}
function onLabStrategyChange() {
  const strat = document.getElementById('lab-strategy-select').value;
  state.lab.strategy = strat;
  if (!strat) { document.getElementById('lab-params-container').innerHTML = ''; updateLabButtons(); return; }
  fetch(`/api/lab/params/${strat}`).then(r => r.json()).then(d => renderLabParams(d.params || [])).catch(() => document.getElementById('lab-params-container').innerHTML = '');
  updateLabButtons();
}
function renderLabParams(params) {
  const container = document.getElementById('lab-params-container');
  if (!params.length) { container.innerHTML = `<p style="font-size:12px;color:var(--text3)">${t('lab_no_params')}</p>`; return; }
  container.innerHTML = `<div style="font-size:12px;color:var(--text3);margin-bottom:8px;font-weight:600">${t('lab_tunable')}</div>` +
    params.map(p => `<div class="param-group">
        <label title="${p.key}">${p.label}</label>
        <input type="range" id="lab-p-${p.key}" min="${p.min}" max="${p.max}" step="${p.type === 'int' ? 1 : (p.max - p.min) / 100}" value="${p.default}"
          oninput="document.getElementById('lab-pv-${p.key}').textContent=parseFloat(this.value).toFixed(p.type==='int'?0:2);state.lab.params['${p.key}']=parseFloat(this.value)"/>
        <span id="lab-pv-${p.key}">${p.default}</span></div>`).join('');
  state.lab.params = {};
  params.forEach(p => { state.lab.params[p.key] = p.default; });
}
function updateLabButtons() {
  const ready = !!(state.lab.dataset && state.lab.strategy);
  document.getElementById('lab-run-btn').disabled = !ready;
  document.getElementById('lab-opt-btn').disabled = !ready;
}
// Date range for Lab/Insight. Falls back to the Research tab's range so the
// three tabs agree on the same window unless the user overrides it locally.
function qrDateRange(prefix) {
  const ownStart = (document.getElementById(prefix + '-start') || {}).value || '';
  const ownEnd = (document.getElementById(prefix + '-end') || {}).value || '';
  const resStart = (document.getElementById('res-start') || {}).value || '';
  const resEnd = (document.getElementById('res-end') || {}).value || '';
  return { start: (ownStart || resStart) || null, end: (ownEnd || resEnd) || null };
}
async function runLabBacktest() {
  if (!state.lab.dataset || !state.lab.strategy) return;
  const btn = document.getElementById('lab-run-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  document.getElementById('lab-results-empty').style.display = 'none';
  document.getElementById('lab-results-content').style.display = 'none';
  try {
    const r = await fetch('/api/lab/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: state.lab.dataset, strategy: state.lab.strategy, params: state.lab.params, ...qrDateRange('lab') }) });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || r.statusText); }
    renderLabResults(await r.json());
  } catch (e) {
    const empty = document.getElementById('lab-results-empty');
    empty.style.display = 'flex'; empty.innerHTML = `<p style="color:var(--red)">${t('error_colon')}${e.message}</p>`;
  }
  btn.disabled = false; btn.innerHTML = labRunBtnHtml();
}
function labRunBtnHtml() { return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> <span>${t('lab_run')}</span>`; }
function renderLabResults(data) {
  document.getElementById('lab-results-content').style.display = 'block';
  document.getElementById('lab-short-badge').style.display = data.allow_short ? 'inline-flex' : 'none';
  const m = data.metrics || {}, bm = data.bh_metrics || {};
  const MDEF = [['Sharpe', 'sharpe', n2], ['CAGR', 'cagr', pct], [t('m_total_return'), 'total_return', pct], [t('m_max_dd'), 'max_drawdown', pct], [t('m_profit_factor'), 'profit_factor', n2], [t('m_win_rate'), 'win_rate', pct]];
  document.getElementById('lab-metrics-grid').innerHTML = MDEF.map(([label, key, fmt]) => {
    const v = m[key], bv = bm[key];
    return `<div class="metric-card"><div class="lbl">${label}</div><div class="val" style="font-size:18px;color:${v >= 0 ? 'var(--green)' : 'var(--red)'}">${fmt(v)}</div><div style="font-size:10px;color:var(--text3);margin-top:2px">B&H: ${fmt(bv)}</div></div>`;
  }).join('');
  const ts = data.timestamps || [];
  Plotly.react('chart-lab-equity', [
    { x: ts, y: data.bh_equity, mode: 'lines', name: 'Buy & Hold', line: { color: '#94a3b8', width: 1.5, dash: 'dot' } },
    { x: ts, y: data.equity, mode: 'lines', name: strategyLabel(state.lab.strategy), line: { color: STRATEGY_COLORS[state.lab.strategy] || '#2dd4bf', width: 2.5 } },
  ], { ...PLOTLY_DARK, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, title: '$' }, hovermode: 'x unified', margin: { l: 50, r: 15, t: 10, b: 40 }, legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID } }, { responsive: true });
  const posColor = data.allow_short
    ? (data.position || []).map(v => v > 0 ? 'rgba(52,211,153,.7)' : v < 0 ? 'rgba(248,113,113,.7)' : 'rgba(100,116,139,.4)')
    : 'rgba(45,212,191,.6)';
  Plotly.react('chart-lab-position', [{ x: ts, y: data.position, type: 'bar', name: 'Position', marker: { color: posColor }, hovertemplate: '%{x}<br>Pos: %{y:.2f}<extra></extra>' }],
    { ...PLOTLY_DARK, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, range: data.allow_short ? [-1.2, 1.2] : [-0.1, 1.2], zeroline: true, zerolinecolor: '#2f3b57' }, margin: { l: 50, r: 15, t: 5, b: 40 } }, { responsive: true });
}
async function runLabOptimizer() {
  if (!state.lab.dataset || !state.lab.strategy) return;
  const btn = document.getElementById('lab-opt-btn');
  btn.disabled = true;
  document.getElementById('lab-opt-progress').style.display = 'block';
  document.getElementById('lab-opt-results').style.display = 'none';
  document.getElementById('lab-opt-bar').style.width = '0%';
  document.getElementById('lab-opt-bar').style.background = 'var(--grad-accent)';
  try {
    const r = await fetch('/api/lab/optimize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: state.lab.dataset, strategy: state.lab.strategy, ...qrDateRange('lab') }) });
    const { job_id } = await r.json();
    const es = new EventSource(`/api/jobs/${job_id}/events`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data); const pct = Math.round(d.progress || 0);
      document.getElementById('lab-opt-bar').style.width = pct + '%';
      document.getElementById('lab-opt-pct').textContent = pct + '%';
      document.getElementById('lab-opt-msg').textContent = jobMessage(d);
      if (d.status === 'done') { document.getElementById('lab-opt-bar').style.background = 'linear-gradient(90deg,#0d9488,#2dd4bf)'; es.close(); fetch(`/api/jobs/${job_id}/result`).then(r2 => r2.json()).then(renderOptResults); btn.disabled = false; }
      else if (d.status === 'error') { document.getElementById('lab-opt-bar').style.background = 'var(--red)'; es.close(); btn.disabled = false; }
    };
    es.onerror = () => { es.close(); btn.disabled = false; };
  } catch (e) { btn.disabled = false; document.getElementById('lab-opt-msg').textContent = t('error_colon') + e.message; }
}
function renderOptResults(data) {
  document.getElementById('lab-opt-results').style.display = 'block';
  const best = data.best || {}, allRes = data.all_results || [], strat = data.strategy || state.lab.strategy;
  document.getElementById('lab-opt-best').innerHTML = `
    <div style="font-size:13px;font-weight:700;color:var(--cyan);margin-bottom:6px">🏆 ${t('lab_best_params')} — ${strategyLabel(strat)}</div>
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:8px">${Object.entries(best.params || {}).map(([k, v]) => `<span style="font-size:12px;padding:3px 10px;border-radius:5px;background:rgba(45,212,191,.1);color:var(--cyan)"><b>${k}</b>: ${v}</span>`).join('')}</div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">${[['Sharpe', best.sharpe, n2], ['CAGR', best.cagr, pct], [t('m_max_dd'), best.max_drawdown, pct], [t('m_win_rate'), best.win_rate, pct]].map(([l, v, f]) => `<span style="font-size:12px;color:var(--text2)">${l}: <b style="color:var(--green)">${f(v)}</b></span>`).join('')}</div>`;
  const header = `<div class="opt-result-row" style="font-weight:700;font-size:11px;color:var(--text3);text-transform:uppercase;padding-bottom:4px"><span>#</span><span>${t('lab_params_col')}</span><span>Sharpe</span><span>CAGR</span><span>${t('m_max_dd')}</span></div>`;
  const rows = allRes.slice(0, 30).map((r, i) => `<div class="opt-result-row${i === 0 ? ' best-row' : ''}">
      <span style="color:var(--text3)">${i + 1}</span>
      <span style="font-size:11px">${Object.entries(r.params || {}).map(([k, v]) => `${k}=${v}`).join(', ')}</span>
      <span style="color:${r.sharpe > 0 ? 'var(--green)' : 'var(--red)'};font-weight:600">${n2(r.sharpe)}</span>
      <span>${pct(r.cagr)}</span><span>${pct(r.max_drawdown)}</span></div>`).join('');
  document.getElementById('lab-opt-table-wrap').innerHTML = header + rows;
  if (best.params) { state.lab.params = { ...best.params }; Object.entries(best.params).forEach(([k, v]) => { const input = document.getElementById(`lab-p-${k}`); const val = document.getElementById(`lab-pv-${k}`); if (input) input.value = v; if (val) val.textContent = v; }); }
}

// ═══════════════════════════════════════════════════════════════ EDGES
async function loadEdges() {
  const body = document.getElementById('edges-body');
  body.innerHTML = `<div class="empty-state"><span class="spinner" style="width:28px;height:28px"></span></div>`;
  try {
    const r = await fetch('/api/edges'); state.edgesData = await r.json();
    renderEdges(state.edgesData);
  } catch (e) { body.innerHTML = `<div class="card"><p class="neg">${t('error_colon')}${esc(e.message)}</p></div>`; }
}
function edgesDirPill(short) { return short ? `<span class="pill both">${t('edges_dir_both')}</span>` : `<span class="pill long">${t('edges_dir_long')}</span>`; }
function renderEdges(data) {
  const r = data.report || {};
  const body = document.getElementById('edges-body');
  if (!r.generated_at) { body.innerHTML = `<div class="card">${t('edges_no_report')}</div>`; return; }
  const tf = r.by_timeframe || {}, plan = r.live_plan || {}, top = r.top || [], alerts = r.alerts || [];
  const when = fmtDateTime(r.generated_at);

  const planRows = Object.keys(plan).map(sym => { const p = plan[sym];
    return `<tr><td><b>${esc(sym)}</b></td><td>${esc(p.strategy)}</td><td>${edgesDirPill(p.allow_short)}</td>
      <td class="pos"><b>${fmtN(p.oos_sharpe)}</b></td><td>${fmtN(p.oos_positive_frac * 100, 0)}%</td>
      <td class="${p.oos_total_return >= 0 ? 'pos' : 'neg'}">${fmtPct(p.oos_total_return)}</td>
      <td class="muted">${esc(p.exchange)}</td></tr>`;
  }).join('') || `<tr><td colspan="7" class="muted">${t('edges_no_live_candidate')}</td></tr>`;

  const alertHtml = alerts.length
    ? alerts.map(a => `<div class="alert"><b>⚠</b> ${esc(edgesAlertText(a))}</div>`).join('')
    : `<div class="ok">✅ ${t('edges_no_alert', { tf: esc(r.live_timeframe) })}</div>`;

  body.innerHTML = `
    <div class="inv-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="metric-card"><div class="lbl">${t('edges_live_tf')}</div><div class="val" style="color:var(--cyan)">${esc(r.live_timeframe)}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_scanned')}</div><div class="val">${r.n_scanned}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_valid')}</div><div class="val pos">${r.n_passed}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_alerts')}</div><div class="val" style="color:${alerts.length ? 'var(--yellow)' : 'var(--green)'}">${alerts.length}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_last_scan')}</div><div class="val" style="font-size:13px;padding-top:8px">${when}</div></div>
    </div>
    <div class="grid-2" style="margin-top:16px">
      <div class="chart-container"><div class="chart-header"><span class="chart-title">📊 ${t('edges_chart_sharpe')}</span></div><div id="edges-sharpe" style="height:260px"></div></div>
      <div class="chart-container"><div class="chart-header"><span class="chart-title">⏱ ${t('edges_chart_tf')}</span></div><div id="edges-tf" style="height:260px"></div></div>
    </div>
    <div class="grid-2">
      <div class="chart-container"><div class="chart-header"><span class="chart-title">🎯 ${t('edges_chart_scatter')}</span></div><div id="edges-scatter" style="height:260px"></div><div class="note" style="padding:0 16px 12px">${t('edges_scatter_note')}</div></div>
      <div class="chart-container"><div class="chart-header"><span class="chart-title">📈 ${t('edges_chart_hist')}</span></div><div id="edges-hist" style="height:260px"></div><div class="note" style="padding:0 16px 12px">${t('edges_hist_note', { n: (data.history || []).length })}</div></div>
    </div>
    ${edgesRigorCard(r.rigor)}
    <div class="card"><div class="card-title"><span class="dot"></span>⚠ ${t('edges_alerts_title')}</div>${alertHtml}</div>
    <div class="card"><div class="card-title"><span class="dot"></span>📡 ${t('edges_live_plan', { tf: esc(r.live_timeframe) })}</div>
      <div class="table-wrap"><table><thead><tr><th>${t('edges_col_symbol')}</th><th>${t('edges_col_rule')}</th><th>${t('edges_col_dir')}</th><th>${t('edges_col_sharpe_oos')}</th><th>${t('edges_col_positive')}</th><th>${t('edges_col_return_oos')}</th><th>${t('edges_col_exchange')}</th></tr></thead><tbody>${planRows}</tbody></table></div>
      <div class="note">${t('edges_plan_note')}</div></div>
    <div class="card"><div class="card-title"><span class="dot"></span>🏆 ${t('edges_all_candidates')}</div>
      <div class="table-wrap"><table><thead><tr><th>${t('edges_col_status')}</th><th>${t('edges_col_exchange')}</th><th>${t('edges_col_symbol')}</th><th>${t('edges_col_tf')}</th><th>${t('edges_col_rule')}</th><th>${t('edges_col_dir')}</th><th>Sharpe</th><th>${t('edges_col_ci')}</th><th>${t('edges_col_psr')}</th><th>${t('edges_col_dsr')}</th><th>${t('edges_col_pbo')}</th><th>${t('edges_col_return_oos')}</th></tr></thead>
      <tbody>${top.slice(0, 20).map(c => {
        const dsr = c.dsr == null || c.dsr !== c.dsr ? '—' : fmtN(c.dsr, 2);
        const dsrCls = (c.deflated_pass) ? 'cell-green' : (c.dsr === c.dsr && c.dsr < 0.9 ? 'cell-red' : '');
        const ci = (c.sharpe_ci_low || c.sharpe_ci_high) ? `${fmtN(c.sharpe_ci_low, 1)}–${fmtN(c.sharpe_ci_high, 1)}` : '—';
        const pbo = c.pbo == null || c.pbo !== c.pbo ? '—' : (c.pbo * 100).toFixed(0) + '%';
        return `<tr><td>${edgesDeployPill(c)}</td><td class="muted">${esc(c.exchange)}</td><td><b>${esc(c.symbol)}</b></td><td>${esc(c.timeframe)}</td><td>${esc(c.strategy)}</td><td>${edgesDirPill(c.allow_short)}</td><td class="pos"><b>${fmtN(c.oos_sharpe)}</b></td><td class="muted" style="font-size:11px">${ci}</td><td>${c.psr != null ? (c.psr * 100).toFixed(0) + '%' : '—'}</td><td class="${dsrCls}">${dsr}</td><td class="muted">${pbo}</td><td class="${c.oos_total_return >= 0 ? 'pos' : 'neg'}">${fmtPct(c.oos_total_return)}</td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="note">${t('edges_deploy_legend')}</div>
      <div class="note">${t('edges_rigor_hint')}</div></div>`;

  buildEdgeCharts(data);
}
function edgesDeployPill(c) {
  // Distinguishes what a bot can actually trade (deployable) from a raw passed
  // edge. Only `deployable` rows reach the live bridge bot;
  // `robust` survived the cross-venue/DSR gate but isn't bridge-supported;
  // `passed` only cleared the loose OOS gate (often illiquid / curve-fit).
  if (c.deployable) return `<span class="pill" style="background:rgba(52,211,153,.18);color:#34d399;border:1px solid rgba(52,211,153,.35)">${t('edges_deploy_deployable')}</span>`;
  if (c.robust) return `<span class="pill" style="background:rgba(34,211,238,.15);color:#22d3ee;border:1px solid rgba(34,211,238,.3)">${t('edges_deploy_robust')}</span>`;
  return `<span class="pill" style="background:rgba(148,163,184,.12);color:#94a3b8;border:1px solid rgba(148,163,184,.25)">${t('edges_deploy_passed')}</span>`;
}
function edgesAlertText(a) {
  if (a.type === 'better_timeframe') return t('edges_alert_better', {
    symbol: a.symbol, ctf: a.candidate_timeframe, csharpe: fmtN(a.candidate_sharpe),
    cstrat: a.candidate_strategy, ltf: a.live_timeframe, lsharpe: fmtN(a.live_sharpe),
  });
  return a.message || '';
}
function buildEdgeCharts(data) {
  const top = (data.report?.top || []).slice(0, 15);
  const tf = data.report?.by_timeframe || {};
  const hist = data.history || [];
  const base = { ...PLOTLY_DARK, margin: { l: 50, r: 20, t: 16, b: 60 } };
  if (top.length) {
    Plotly.react('edges-sharpe', [{
      type: 'bar', x: top.map(c => `${c.symbol} ${c.timeframe}`), y: top.map(c => c.oos_sharpe),
      marker: { color: top.map(c => c.oos_sharpe >= 0.5 ? '#34d399' : c.oos_sharpe >= 0.2 ? '#2dd4bf' : '#fbbf24') },
      hovertemplate: '%{x}<br>Sharpe: %{y:.2f}<extra></extra>',
    }], { ...base, xaxis: { gridcolor: GRID, tickangle: -40, tickfont: { size: 10 } }, yaxis: { gridcolor: GRID } }, { responsive: true, displayModeBar: false });
  }
  const tfKeys = Object.keys(tf).sort();
  if (tfKeys.length) {
    Plotly.react('edges-tf', [{
      type: 'pie', hole: .55, labels: tfKeys, values: tfKeys.map(k => tf[k].passed),
      marker: { colors: ['#2dd4bf', '#818cf8', '#34d399', '#fbbf24', '#f87171', '#60a5fa'] },
      textinfo: 'label+value', hovertemplate: '%{label}: %{value}<extra></extra>',
    }], { ...base, showlegend: true, legend: { font: { size: 11 } } }, { responsive: true, displayModeBar: false });
  }
  if (top.length) {
    Plotly.react('edges-scatter', [{
      type: 'scatter', mode: 'markers', x: top.map(c => c.oos_sharpe), y: top.map(c => c.oos_total_return * 100),
      marker: { size: top.map(c => Math.max(7, c.trades_per_split * 0.6)), color: top.map(c => c.oos_total_return >= 0 ? 'rgba(52,211,153,.7)' : 'rgba(248,113,113,.65)') },
      text: top.map(c => `${c.symbol} · ${c.timeframe} · ${c.strategy}`),
      hovertemplate: '%{text}<br>Sharpe: %{x:.2f}<br>%{y:.1f}%<extra></extra>',
    }], { ...base, xaxis: { gridcolor: GRID, title: 'Sharpe OOS' }, yaxis: { gridcolor: GRID, title: t('edges_oos_return') + ' %', ticksuffix: '%' } }, { responsive: true, displayModeBar: false });
  }
  if (hist.length > 1) {
    Plotly.react('edges-hist', [{
      type: 'scatter', mode: 'lines+markers', fill: 'tozeroy', x: hist.map(h => (h.generated_at || '').slice(0, 10)), y: hist.map(h => h.n_passed),
      line: { color: '#2dd4bf', width: 2 }, fillcolor: 'rgba(45,212,191,.1)',
    }], { ...base, xaxis: { gridcolor: GRID, tickfont: { size: 10 } }, yaxis: { gridcolor: GRID, rangemode: 'tozero' } }, { responsive: true, displayModeBar: false });
  }
}
// ── Pipeline progress bar helpers ────────────────────────────────────────────
const EPB_STAGES = ['data_refresh', 'wf_scan', 'pair_rotation'];
const EPB_STAGE_FA = { data_refresh: '↓ دانلود دیتا', wf_scan: '🔬 اسکن walk-forward', pair_rotation: '🔄 چرخش جفت‌ارز' };
let _epbPollTimer = null;

function epbShow(step, mins) {
  document.getElementById('edges-pipeline-bar').style.display = 'block';
  EPB_STAGES.forEach(s => {
    const el = document.getElementById('epb-' + s);
    if (!el) return;
    const idx = EPB_STAGES.indexOf(s), cur = EPB_STAGES.indexOf(step || '');
    if (idx < cur) {
      el.style.background = 'rgba(34,197,94,.15)'; el.style.color = 'var(--green)';
    } else if (idx === cur) {
      el.style.background = 'rgba(251,191,36,.22)'; el.style.color = '#fbbf24';
    } else {
      el.style.background = 'var(--bg2)'; el.style.color = 'var(--text2)';
    }
  });
  const det = document.getElementById('epb-detail');
  if (det) det.textContent = mins != null ? `مدت اجرا: ${mins} دقیقه${mins > 60 ? ' — اسکن کامل ۲-۵ ساعت طول می‌کشد' : ''}` : '';
}

function epbHide() {
  const bar = document.getElementById('edges-pipeline-bar');
  if (bar) bar.style.display = 'none';
  if (_epbPollTimer) { clearInterval(_epbPollTimer); _epbPollTimer = null; }
}

function epbStartPolling() {
  if (_epbPollTimer) clearInterval(_epbPollTimer);
  _epbPollTimer = setInterval(async () => {
    try {
      const r = await fetch('/api/edges/pipeline-status');
      const ps = await r.json();
      if (ps.state === 'running') {
        epbShow(ps.step, ps.running_minutes);
      } else if (ps.state === 'idle') {
        epbHide();
        document.getElementById('edges-rescan-btn').disabled = false;
        document.getElementById('edges-status').textContent = ps.last_run?.ok ? t('edges_scan_done_short') || 'اسکن کامل شد' : t('edges_scan_failed_short') || 'اسکن ناموفق';
        loadEdges();
      }
    } catch (_) { /* ignore transient fetch errors */ }
  }, 20000);  // poll every 20 s
}

async function rescanEdges() {
  const btn = document.getElementById('edges-rescan-btn');
  const st = document.getElementById('edges-status');
  btn.disabled = true; st.textContent = t('edges_scanning');

  // Check current pipeline state before firing
  try {
    const psR = await fetch('/api/edges/pipeline-status');
    const ps = await psR.json();
    if (ps.state === 'running' && !ps.stale) {
      epbShow(ps.step, ps.running_minutes);
      epbStartPolling();
      st.textContent = `مرحله: ${EPB_STAGE_FA[ps.step] || ps.step || '...'} (${ps.running_minutes || 0} دقیقه)`;
      return;
    }
  } catch (_) { /* fall through to start */ }

  try {
    const r = await fetch('/api/edges/refresh', { method: 'POST' });
    const { job_id } = await r.json();
    const ev = new EventSource('/api/jobs/' + job_id + '/events');
    ev.onmessage = e => {
      const d = JSON.parse(e.data);
      const step = d.message_params?.step;
      const mins = d.message_params?.minutes;
      if (step) epbShow(step, mins);
      st.textContent = jobMessage(d) + (d.progress && d.progress < 100 ? ` (${Math.round(d.progress)}%)` : '');
      if (d.status === 'done') { ev.close(); epbHide(); btn.disabled = false; loadEdges(); }
      if (d.status === 'error') { ev.close(); epbHide(); btn.disabled = false; st.textContent = t('error_colon') + (d.error || jobMessage(d)); }
    };
    ev.onerror = () => {
      ev.close();
      // SSE closed (normal after ~3 min) — switch to polling the pipeline-status endpoint
      epbStartPolling();
      fetch('/api/edges/pipeline-status').then(r2 => r2.json()).then(ps => {
        if (ps.state === 'running') {
          epbShow(ps.step, ps.running_minutes);
          st.textContent = `مرحله: ${EPB_STAGE_FA[ps.step] || ps.step || '...'} (${ps.running_minutes || 0} دقیقه)`;
        } else {
          btn.disabled = false;
        }
      }).catch(() => { btn.disabled = false; });
    };
  } catch (e) { st.textContent = t('error_colon') + e.message; btn.disabled = false; epbHide(); }

  // Show the bar immediately with "init" step
  epbShow('init', 0);
}

// ═══════════════════════════════════════════════════════════════ EDGES RIGOR CARD
function edgesRigorCard(rig) {
  if (!rig) return '';
  const pbo = rig.median_pbo == null ? '—' : (rig.median_pbo * 100).toFixed(0) + '%';
  const pboColor = rig.median_pbo == null ? 'var(--text2)' : rig.median_pbo > 0.5 ? 'var(--red)' : rig.median_pbo > 0.3 ? 'var(--yellow)' : 'var(--green)';
  return `<div class="card"><div class="card-title"><span class="dot"></span>🛡 ${t('edges_rigor_title')}</div>
    <div class="metric-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">
      <div class="metric-card"><div class="lbl">${t('edges_rigor_trials')}</div><div class="val" style="color:var(--cyan)">${rig.n_trials}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_rigor_pbo')}</div><div class="val" style="color:${pboColor}">${pbo}</div></div>
      <div class="metric-card"><div class="lbl">${t('edges_rigor_deflated')}</div><div class="val" style="color:${rig.n_deflated_pass ? 'var(--green)' : 'var(--yellow)'}">${rig.n_deflated_pass} <span style="font-size:13px;color:var(--text3)">(${(rig.deflated_frac * 100).toFixed(0)}%)</span></div></div>
    </div>
    <div class="note">${t('edges_rigor_hint')}</div></div>`;
}

// ═══════════════════════════════════════════════════════════════ CROSS-EXCHANGE
function initCrossExchange() {
  if (state.cxSymbols) return;            // already loaded
  fetch('/api/cross-exchange/symbols').then(r => r.json()).then(d => {
    state.cxSymbols = d.symbols || {};
    const sel = document.getElementById('cx-symbol');
    const syms = Object.keys(state.cxSymbols).sort();
    sel.innerHTML = syms.map(s => `<option value="${s}">${s}</option>`).join('');
    onCxSymbolChange();
  });
}
function onCxSymbolChange() {
  const sym = document.getElementById('cx-symbol').value;
  const tfs = Object.keys((state.cxSymbols || {})[sym] || {}).sort();
  document.getElementById('cx-tf').innerHTML = tfs.map(tf => `<option value="${tf}">${tf}</option>`).join('');
}
async function runCrossExchange() {
  const sym = document.getElementById('cx-symbol').value;
  const tf = document.getElementById('cx-tf').value;
  if (!sym || !tf) return;
  const body = document.getElementById('crossex-body');
  body.innerHTML = `<div class="empty-state"><span class="spinner" style="width:28px;height:28px"></span></div>`;
  try {
    const r = await fetch(`/api/cross-exchange?symbol=${encodeURIComponent(sym)}&timeframe=${encodeURIComponent(tf)}`);
    state.cxData = await r.json();
    renderCrossExchange(state.cxData);
  } catch (e) { body.innerHTML = `<div class="card"><p class="neg">${t('error_colon')}${esc(e.message)}</p></div>`; }
}
function renderCrossExchange(d) {
  const body = document.getElementById('crossex-body');
  if (d.insufficient) { body.innerHTML = `<div class="card">${t('cx_insufficient')}</div>`; return; }
  const ll = (d.lead_lag || []).map(x => `<tr><td>${esc(x.a)} ↔ ${esc(x.b)}</td><td><b>${x.best_lag}</b></td><td>${fmtN(x.corr, 2)}</td><td class="muted">${esc(x.leader)}</td></tr>`).join('');
  const co = (d.cointegration || []).map(x => `<tr><td>${esc(x.a)} ↔ ${esc(x.b)}</td><td class="${x.cointegrated ? 'cell-green' : ''}">${fmtN(x.pvalue, 3)}</td><td>${fmtN(x.hedge_ratio, 2)}</td><td class="${Math.abs(x.spread_z) > 2 ? 'cell-yellow' : 'muted'}">${fmtN(x.spread_z, 2)}</td><td>${x.cointegrated ? '✅' : '—'}</td></tr>`).join('');
  const bs = (d.basis || []).map(x => `<tr><td>${esc(x.spot)}</td><td>${esc(x.derivative)}</td><td>${x.kind === 'cross_venue' ? `<span class="badge" style="background:rgba(148,163,184,.15);color:#94a3b8">${t('cx_kind_cross')}</span>` : `<span class="badge badge-cyan">${t('cx_kind_basis')}</span>`}</td><td class="${x.basis_now_pct >= 0 ? 'pos' : 'neg'}">${fmtN(x.basis_now_pct, 3)}%</td><td class="muted">${fmtN(x.basis_mean_pct, 3)}%</td><td class="muted">${fmtN(x.basis_std_pct, 3)}%</td></tr>`).join('');
  const liq = (d.liquidity || []).map(x => `<tr><td>${esc(x.venue)}</td><td>$${fmtNum(Math.round(x.dollar_volume))}</td></tr>`).join('');
  body.innerHTML = `
    <div class="card"><div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
      <span class="badge badge-cyan">${d.symbol} · ${d.timeframe}</span>
      <span style="font-size:12px;color:var(--text3)">${t('cx_venues')}: ${d.n_venues} · ${t('cx_bars')}: ${fmtNum(d.n_bars)}</span>
      ${(d.venues || []).map(v => `<span class="tf-badge">${esc(v)}</span>`).join('')}
    </div></div>
    <div class="grid-2">
      <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_leadlag')}</div>
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_pair')}</th><th>${t('cx_col_lag')}</th><th>${t('cx_col_corr')}</th><th>${t('cx_col_leader')}</th></tr></thead><tbody>${ll || `<tr><td colspan="4" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div>
        <div class="note">${t('cx_leadlag_hint')}</div></div>
      <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_coint')}</div>
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_pair')}</th><th>${t('cx_col_pvalue')}</th><th>${t('cx_col_hedge')}</th><th>${t('cx_col_z')}</th><th>${t('cx_col_coint')}</th></tr></thead><tbody>${co || `<tr><td colspan="5" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div>
        <div class="note">${t('cx_coint_hint')}</div></div>
    </div>
    <div class="grid-2">
      <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_basis')}</div>
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_spot')}</th><th>${t('cx_col_deriv')}</th><th>${t('cx_col_kind')}</th><th>${t('cx_col_basis_now')}</th><th>${t('cx_col_basis_mean')}</th><th>${t('cx_col_basis_std')}</th></tr></thead><tbody>${bs || `<tr><td colspan="6" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div>
        <div class="note">${t('cx_basis_hint')}</div></div>
      <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_liquidity')}</div>
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_venue')}</th><th>${t('cx_col_dvol')}</th></tr></thead><tbody>${liq || `<tr><td colspan="2" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div></div>
    </div>`;
}

async function runCxScan() {
  const tf = document.getElementById('cx-tf').value || '';
  const body = document.getElementById('crossex-body');
  body.innerHTML = `<div class="empty-state"><span class="spinner" style="width:28px;height:28px"></span> ${t('cx_scanning')}</div>`;
  try {
    const r = await fetch(`/api/cross-exchange/scan${tf ? '?timeframe=' + encodeURIComponent(tf) : ''}`);
    const d = await r.json();
    const typeColor = { stat_arb: 'var(--green)', lead_lag: 'var(--cyan)', dislocation: 'var(--yellow)' };
    const confColor = { high: 'var(--green)', medium: 'var(--yellow)', low: 'var(--text3)' };
    const rows = (d.opportunities || []).map(o => `<tr>
      <td><span class="badge" style="background:${(typeColor[o.type] || '#94a3b8')}22;color:${typeColor[o.type] || '#94a3b8'}">${esc(o.type)}</span></td>
      <td><b>${esc(o.symbol)}</b></td><td>${esc(o.timeframe)}</td>
      <td class="pos"><b>${fmtN(o.score, 2)}</b></td>
      <td><span class="badge" style="background:${(confColor[o.confidence] || '#94a3b8')}22;color:${confColor[o.confidence] || '#94a3b8'}">${t('cx_conf_' + (o.confidence || 'low'))}</span></td>
      <td class="muted">${fmtN(o.gap_pct, 2)}%</td>
      <td class="${(o.est_pnl_usd || 0) >= 0 ? 'pos' : 'neg'}">$${fmtN(o.est_pnl_usd, 2)}</td>
      <td style="font-size:12px">${esc(o.action)}</td>
      <td class="muted" style="font-size:11px">${(o.venues || []).join(', ')}</td></tr>`).join('')
      || `<tr><td colspan="9" class="muted">${t('no_data')}</td></tr>`;
    body.innerHTML = `<div class="card"><div class="card-title"><span class="dot"></span>🎯 ${t('cx_scan_title')} <span class="badge badge-cyan" style="margin-inline-start:8px">${d.n_scanned}</span></div>
      <div class="table-wrap"><table><thead><tr>
        <th>${t('cx_col_type')}</th><th>${t('cx_col_symbol')}</th><th>${t('cx_col_tf')}</th>
        <th title="${esc(t('cx_score_tip'))}">${t('cx_col_score')} ℹ️</th>
        <th>${t('cx_col_confidence')}</th><th>${t('cx_col_gap')}</th>
        <th title="${esc(t('cx_pnl_tip'))}">${t('cx_col_pnl')} ℹ️</th>
        <th>${t('cx_col_action')}</th><th>${t('cx_col_venues')}</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
      <div class="note">${t('cx_scan_hint')}</div>
      <div class="note">${t('cx_pnl_tip')}</div></div>
    <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_scan_guide_title')}</div>
      <p style="font-size:13px;line-height:1.8;margin:6px 0">${t('cx_guide_stat_arb')}</p>
      <p style="font-size:13px;line-height:1.8;margin:6px 0">${t('cx_guide_lead_lag')}</p>
      <p style="font-size:13px;line-height:1.8;margin:6px 0">${t('cx_guide_dislocation')}</p>
      <div class="note" style="margin-top:8px">${t('cx_guide_disclaimer')}</div></div>`;
  } catch (e) { body.innerHTML = `<div class="card"><p class="neg">${t('error_colon')}${esc(e.message)}</p></div>`; }
}

// ═══════════════════════════════════════════════════════════════ PORTFOLIO
let pfMethod = 'hrp';
function initPortfolio() {
  const el = document.getElementById('pf-datasets');
  if (!el) return;
  el.innerHTML = state.inventory.map(item => `<div class="ds-item" onclick="toggleCb(this)" data-file="${item.file}">
      <input type="checkbox"/><div style="font-weight:600;font-size:13px">${item.symbol} <span class="tf-badge">${item.timeframe}</span> <span style="font-size:10px;color:var(--text3)">${item.exchange}</span></div></div>`).join('')
    || `<div class="empty-state" style="padding:24px"><p>${t('no_data')}</p></div>`;
}
function setPfMethod(m, btn) { pfMethod = m; btn.parentElement.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active'); }
async function runPortfolio() {
  const files = [...document.querySelectorAll('#pf-datasets .ds-item.selected')].map(el => el.dataset.file);
  if (files.length < 2) { alert(t('pf_need_two')); return; }
  const body = document.getElementById('pf-body');
  body.innerHTML = `<div class="empty-state"><span class="spinner" style="width:28px;height:28px"></span></div>`;
  try {
    const r = await fetch('/api/portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files, method: pfMethod }) });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || r.statusText); }
    state.pfData = await r.json();
    renderPortfolio(state.pfData);
  } catch (e) { body.innerHTML = `<div class="card"><p class="neg">${t('error_colon')}${esc(e.message)}</p></div>`; }
}
function renderPortfolio(d) {
  const body = document.getElementById('pf-body');
  const w = d.weights || {}, m = d.metrics || {}, sz = d.sizing || {};
  const cols = Object.keys(w);
  const metrics = [
    [t('pf_n_assets'), m.n_assets, 'var(--cyan)'],
    [t('pf_div_ratio'), fmtN(m.diversification_ratio, 2), 'var(--green)'],
    [t('pf_avg_corr'), fmtN(m.avg_pairwise_corr, 2), 'var(--yellow)'],
    [t('pf_port_vol'), (m.portfolio_vol_per_bar * 100).toFixed(3) + '%', 'var(--purple)'],
  ];
  const sizingRows = cols.map(c => `<tr><td><b>${esc(c)}</b></td><td>${(w[c] * 100).toFixed(1)}%</td><td class="${(sz[c]?.kelly?.fractional_kelly || 0) >= 0 ? 'pos' : 'neg'}">${fmtN(sz[c]?.kelly?.fractional_kelly, 2)}</td><td>${fmtN(sz[c]?.vol_target_leverage, 2)}×</td></tr>`).join('');
  const bt = d.backtest || {}, bm = bt.metrics || {}, em = bt.equal_weight_metrics || {};
  const beat = (bm.total_return || 0) >= (em.total_return || 0);
  const btCard = bt.equity ? `
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_backtest')}
      <span class="badge ${beat ? 'badge-green' : 'badge-red'}" style="margin-inline-start:8px">${beat ? t('pf_beats_ew') : t('pf_below_ew')}</span></div>
      <div class="metric-grid" style="margin-bottom:12px">
        ${[['Total', 'total_return', true], ['CAGR', 'cagr', true], ['Sharpe', 'sharpe', false], ['Max DD', 'max_drawdown', true]].map(([l, k, isPct]) => {
          const v = bm[k], ev = em[k];
          const fmtV = isPct ? (x => (x * 100).toFixed(1) + '%') : (x => fmtN(x, 2));
          return `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${(v || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${fmtV(v)}</div><div style="font-size:10px;color:var(--text3);margin-top:2px">1/N: ${fmtV(ev)}</div></div>`;
        }).join('')}
      </div>
      <div id="pf-equity-chart" style="height:260px"></div>
      <div class="note">${t('pf_backtest_hint')}</div></div>` : '';
  body.innerHTML = `
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_weights')} <span class="badge badge-cyan" style="margin-inline-start:8px">${d.method}</span></div><div id="pf-weights-chart" style="height:260px"></div></div>
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_metrics')}</div><div class="metric-grid">${metrics.map(([l, v, c]) => `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${c}">${v}</div></div>`).join('')}</div></div>
    ${btCard}
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_sizing')}</div>
      <div class="table-wrap"><table><thead><tr><th>${t('pf_col_asset')}</th><th>${t('pf_col_weight')}</th><th>${t('pf_col_kelly')}</th><th>${t('pf_col_vol_lev')}</th></tr></thead><tbody>${sizingRows}</tbody></table></div></div>`;
  if (bt.equity) {
    Plotly.react('pf-equity-chart', [
      { x: bt.timestamps, y: bt.equal_weight_equity, mode: 'lines', name: '1/N (' + t('pf_equal') + ')', line: { color: '#94a3b8', width: 1.5, dash: 'dot' } },
      { x: bt.timestamps, y: bt.equity, mode: 'lines', name: d.method, line: { color: '#2dd4bf', width: 2.5 } },
    ], { ...PLOTLY_DARK, margin: { l: 50, r: 15, t: 10, b: 40 }, xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, title: '×' }, hovermode: 'x unified', legend: { bgcolor: 'rgba(0,0,0,.4)', bordercolor: GRID } }, { responsive: true });
  }
  Plotly.react('pf-weights-chart', [{
    type: 'bar', x: cols, y: cols.map(c => w[c] * 100),
    marker: { color: '#2dd4bf' }, hovertemplate: '%{x}<br>%{y:.1f}%<extra></extra>',
  }], { ...PLOTLY_DARK, margin: { l: 50, r: 20, t: 16, b: 80 }, xaxis: { gridcolor: GRID, tickangle: -30 }, yaxis: { gridcolor: GRID, ticksuffix: '%' } }, { responsive: true, displayModeBar: false });
}

// ═══════════════════════════════════════════════════════════════ MODELS (ML/RL)
function loadModels() {
  // RL recommendations
  const rlBody = document.getElementById('rl-reco-body');
  rlBody.innerHTML = `<div class="empty-state" style="padding:24px"><span class="spinner"></span></div>`;
  fetch('/api/rl/recommend?timeframe=15m&top_n=12').then(r => r.json()).then(d => {
    const cards = (d.recommendations || []).slice(0, 12).map((x, i) => {
      const sc = x.rl_score;
      const barColor = sc >= 55 ? '#34d399' : sc >= 45 ? '#22d3ee' : '#fbbf24';
      return `<div style="background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <div style="font-weight:800;font-size:14px">${esc(x.symbol)}</div>
            <div style="font-size:10px;opacity:.45">${esc(x.exchange)}</div>
          </div>
          <div style="font-weight:800;font-size:18px;color:${barColor}">${sc}</div>
        </div>
        <div style="height:5px;background:rgba(255,255,255,.07);border-radius:99px;overflow:hidden">
          <div style="height:100%;width:${Math.max(4,sc)}%;background:${barColor};border-radius:99px"></div>
        </div>
        <div style="display:flex;gap:8px;font-size:10px;opacity:.55;flex-wrap:wrap">
          <span>regimes: <b>${x.regime_changes}</b></span>
          <span>density: <b>${fmtN(x.reward_density,2)}</b></span>
          <span>pred: <b>${fmtN(x.low_predictability,2)}</b></span>
        </div>
      </div>`;
    }).join('');
    rlBody.innerHTML = `<div style="font-size:11px;color:var(--text3);margin-bottom:10px">${d.n_evaluated} ${t('mdl_rl_evaluated')}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px">${cards || `<p class="muted">${t('no_data')}</p>`}</div>`;
  }).catch(() => rlBody.innerHTML = `<p class="muted">${t('no_data')}</p>`);

  // ML recommendations (mirror of RL, powered by /api/ml/recommend)
  const mlBody = document.getElementById('ml-reco-body');
  if (mlBody) {
    mlBody.innerHTML = `<div class="empty-state" style="padding:24px"><span class="spinner"></span></div>`;
    fetch('/api/ml/recommend?timeframe=15m&top_n=12').then(r => r.json()).then(d => {
      const cards = (d.recommendations || []).slice(0, 12).map((x) => {
        const sc = x.ml_score;
        const barColor = sc >= 55 ? '#34d399' : sc >= 45 ? '#22d3ee' : '#fbbf24';
        return `<div style="background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-weight:800;font-size:14px">${esc(x.symbol)}</div>
              <div style="font-size:10px;opacity:.45">${esc(x.exchange)}</div>
            </div>
            <div style="font-weight:800;font-size:18px;color:${barColor}">${sc}</div>
          </div>
          <div style="height:5px;background:rgba(255,255,255,.07);border-radius:99px;overflow:hidden">
            <div style="height:100%;width:${Math.max(4,sc)}%;background:${barColor};border-radius:99px"></div>
          </div>
          <div style="display:flex;gap:8px;font-size:10px;opacity:.55;flex-wrap:wrap">
            <span>autocorr: <b>${fmtN(x.autocorr_1,3)}</b></span>
            <span>hurst: <b>${fmtN(x.hurst,2)}</b></span>
            <span>stat: <b>${fmtN(x.stationarity,2)}</b></span>
          </div>
        </div>`;
      }).join('');
      mlBody.innerHTML = `<div style="font-size:11px;color:var(--text3);margin-bottom:10px">${d.n_evaluated} ${t('mdl_rl_evaluated')}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px">${cards || `<p class="muted">${t('no_data')}</p>`}</div>`;
    }).catch(() => mlBody.innerHTML = `<p class="muted">${t('no_data')}</p>`);
  }

  // ML eval dataset dropdown
  const sel = document.getElementById('ml-dataset');
  if (sel && !sel.options.length) {
    sel.innerHTML = state.inventory.map(i => `<option value="${i.file}">${i.symbol} · ${i.exchange} · ${i.timeframe}</option>`).join('');
  }
  loadExperiments();
  loadMoneyFlow();
}
function _mfCard(x, color) {
  return `<div style="background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="font-weight:800;font-size:14px">${esc(x.symbol)}</div>
        <div style="font-size:10px;opacity:.45">${esc(x.exchange)}</div>
      </div>
      <div style="font-weight:800;font-size:18px;color:${color}">${x.money_flow_score}</div>
    </div>
    <div style="height:5px;background:rgba(255,255,255,.07);border-radius:99px;overflow:hidden">
      <div style="height:100%;width:${Math.max(4,x.money_flow_score)}%;background:${color};border-radius:99px"></div>
    </div>
    <div style="display:flex;gap:8px;font-size:10px;opacity:.55;flex-wrap:wrap">
      <span>cmf: <b>${fmtN(x.cmf,3)}</b></span>
      <span>rvol: <b>${fmtN(x.rvol,2)}</b></span>
      <span>obv: <b>${fmtN(x.obv_slope,3)}</b></span>
    </div>
  </div>`;
}
function loadMoneyFlow() {
  const inBody = document.getElementById('mf-inflow-body');
  const outBody = document.getElementById('mf-outflow-body');
  if (!inBody || !outBody) return;
  inBody.innerHTML = `<div class="empty-state" style="padding:24px"><span class="spinner"></span></div>`;
  outBody.innerHTML = `<div class="empty-state" style="padding:24px"><span class="spinner"></span></div>`;
  fetch('/api/money-flow/score?timeframe=15m&top_n=8').then(r => r.json()).then(d => {
    const inflowCards = (d.top_inflow || []).map(x => _mfCard(x, '#34d399')).join('');
    const outflowCards = (d.top_outflow || []).map(x => _mfCard(x, '#f87171')).join('');
    inBody.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">${inflowCards || `<p class="muted">${t('no_data')}</p>`}</div>`;
    outBody.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">${outflowCards || `<p class="muted">${t('no_data')}</p>`}</div>`;
  }).catch(() => {
    inBody.innerHTML = `<p class="muted">${t('no_data')}</p>`;
    outBody.innerHTML = `<p class="muted">${t('no_data')}</p>`;
  });
}
async function runMlEval() {
  const file = document.getElementById('ml-dataset').value;
  if (!file) return;
  const optimize = document.getElementById('ml-optimize').checked;
  const btn = document.getElementById('ml-eval-btn');
  const body = document.getElementById('ml-eval-body');
  btn.disabled = true;
  body.innerHTML = `<div style="display:flex;align-items:center;gap:8px;color:var(--text3)"><span class="spinner"></span> ${t('running')}</div>`;
  try {
    const r = await fetch('/api/ml/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file, optimize }) });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || r.statusText); }
    const d = await r.json();
    const vColor = { predictable: 'var(--green)', weak: 'var(--yellow)', noise: 'var(--red)' }[d.verdict] || 'var(--text2)';
    body.innerHTML = `<div class="metric-grid">
        <div class="metric-card"><div class="lbl">${t('mdl_ml_auc')}</div><div class="val" style="color:${vColor}">${fmtN(d.mean_auc, 3)}</div></div>
        <div class="metric-card"><div class="lbl">${t('mdl_ml_acc')}</div><div class="val" style="font-size:18px">${(d.mean_accuracy * 100).toFixed(1)}%</div></div>
        <div class="metric-card"><div class="lbl">${t('mdl_ml_verdict')}</div><div class="val" style="font-size:18px;color:${vColor}">${t('verdict_' + d.verdict)}</div></div>
        <div class="metric-card"><div class="lbl">${t('mdl_ml_folds')}</div><div class="val" style="font-size:13px;padding-top:8px;color:var(--text2)">${(d.fold_auc || []).map(a => a.toFixed(2)).join(', ')}</div></div>
      </div>${d.best_params ? `<div class="note">params: ${Object.entries(d.best_params).map(([k, v]) => k + '=' + v).join(', ')} ${d.note ? '· ' + esc(d.note) : ''}</div>` : ''}`;
    loadExperiments();
  } catch (e) { body.innerHTML = `<p class="neg">${t('error_colon')}${esc(e.message)}</p>`; }
  btn.disabled = false;
}
function loadExperiments() {
  fetch('/api/experiments').then(r => r.json()).then(d => {
    const runs = d.runs || [];
    const el = document.getElementById('experiments-body');
    if (!runs.length) { el.innerHTML = `<div class="empty-state" style="padding:24px"><p>${t('mdl_exp_empty')}</p></div>`; return; }

    // Helper: color a metric value based on known thresholds
    function metricColor(key, val) {
      if (typeof val !== 'number') return 'var(--text2)';
      const k = key.toLowerCase();
      if (k.includes('auc')) return val >= 0.55 ? 'var(--green)' : val >= 0.52 ? 'var(--yellow)' : 'var(--red)';
      if (k.includes('sharpe') || k.includes('sortino')) return val >= 1.0 ? 'var(--green)' : val >= 0.5 ? 'var(--yellow)' : 'var(--red)';
      if (k.includes('return') || k.includes('pnl')) return val > 0 ? 'var(--green)' : val < 0 ? 'var(--red)' : 'var(--text2)';
      if (k.includes('drawdown') || k.includes('dd')) return val < -0.2 ? 'var(--red)' : val < -0.1 ? 'var(--yellow)' : 'var(--green)';
      if (k.includes('accuracy') || k.includes('win')) return val >= 0.55 ? 'var(--green)' : val >= 0.48 ? 'var(--yellow)' : 'var(--red)';
      return 'var(--text2)';
    }
    function metricFmt(key, val) {
      if (typeof val !== 'number') return String(val);
      const k = key.toLowerCase();
      if (k.includes('return') || k.includes('pnl') || k.includes('drawdown') || k.includes('accuracy') || k.includes('win') || k.includes('auc')) return (val * (k.includes('return') || k.includes('drawdown') || k.includes('accuracy') || k.includes('win') ? 100 : 1)).toFixed(2) + (k.includes('return') || k.includes('drawdown') || k.includes('accuracy') || k.includes('win') ? '%' : '');
      return val.toFixed(3);
    }

    // Summary chart: trend of first numeric metric over experiments
    const chartMetricKey = runs.length > 1 ? (() => {
      const m0 = runs[0].metrics || {};
      return Object.keys(m0).find(k => typeof m0[k] === 'number') || null;
    })() : null;

    const cards = runs.map(r => {
      const m = r.metrics || {};
      const pills = Object.entries(m).slice(0, 6).map(([k, v]) =>
        `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:4px 8px;min-width:70px">
           <span style="font-size:10px;opacity:.5;text-transform:uppercase;letter-spacing:.04em">${k.replace(/_/g,' ')}</span>
           <span style="font-size:14px;font-weight:700;color:${metricColor(k,v)}">${metricFmt(k,v)}</span>
         </span>`
      ).join('');
      const paramStr = Object.entries(r.params || {}).slice(0, 4).map(([k,v]) => `<span style="font-size:10px;opacity:.45">${k}=<b>${typeof v === 'number' ? v : esc(String(v))}</b></span>`).join(' · ');
      return `<div style="background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 12px;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap">
          <span style="font-weight:700;font-size:13px">${esc(r.name)}</span>
          <span style="font-size:10px;opacity:.4">${fmtDateTime(r.ts * 1000)}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:${paramStr ? '8px' : '0'}">${pills}</div>
        ${paramStr ? `<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">${paramStr}</div>` : ''}
      </div>`;
    }).join('');

    let trendHtml = '';
    if (chartMetricKey && runs.length >= 3) {
      trendHtml = `<div style="margin-bottom:10px;font-size:11px;opacity:.5">تغییرات <b>${chartMetricKey}</b> در ${runs.length} اجرا</div>
        <div id="exp-trend-chart" style="height:140px;margin-bottom:12px"></div>`;
    }

    el.innerHTML = trendHtml + cards;

    if (chartMetricKey && runs.length >= 3) {
      const xs = runs.map(r => fmtDateTime(r.ts * 1000));
      const ys = runs.map(r => typeof r.metrics[chartMetricKey] === 'number' ? r.metrics[chartMetricKey] : null);
      Plotly.react('exp-trend-chart', [{
        x: xs, y: ys, mode: 'lines+markers', type: 'scatter',
        line: { color: 'var(--cyan)', width: 2 },
        marker: { size: 5, color: ys.map(v => {
          const c = metricColor(chartMetricKey, v);
          return c === 'var(--green)' ? '#34d399' : c === 'var(--yellow)' ? '#fbbf24' : '#f87171';
        }) },
        hovertemplate: `<b>${esc(chartMetricKey)}</b>: %{y:.4f}<extra></extra>`,
      }], {
        ...PLOTLY_DARK, height: 140,
        margin: { l: 50, r: 10, t: 5, b: 50 },
        xaxis: { gridcolor: GRID, tickfont: { size: 9 } },
        yaxis: { gridcolor: GRID, tickfont: { size: 9 } },
      }, { responsive: true, displayModeBar: false });
    }
  });
}

// ═══════════════════════════════════════════════════════════════ DATA QUALITY + FORWARD-TEST
function loadQuality() {
  const stats = document.getElementById('quality-stats');
  const table = document.getElementById('quality-table');
  table.innerHTML = `<div class="empty-state" style="padding:24px"><span class="spinner"></span></div>`;
  fetch('/api/quality').then(r => r.json()).then(d => {
    const tt = d.totals || {};
    const hColor = d.health_pct >= 90 ? 'var(--green)' : d.health_pct >= 70 ? 'var(--yellow)' : 'var(--red)';
    stats.innerHTML = [
      [t('q_health'), d.health_pct + '%', hColor],
      [t('q_datasets'), tt.datasets, 'var(--cyan)'],
      [t('q_clean'), tt.clean, 'var(--green)'],
      [t('q_with_gaps'), tt.with_gaps, 'var(--yellow)'],
      [t('q_with_malformed'), tt.with_malformed, 'var(--red)'],
    ].map(([l, v, c]) => `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="color:${c}">${v}</div></div>`).join('');
    const rows = (d.items || []).slice(0, 80).map(i => `<tr>
      <td style="font-size:11px">${esc(i.symbol)} <span class="muted">${esc(i.exchange)}·${esc(i.timeframe)}</span></td>
      <td class="muted">${fmtNum(i.rows)}</td><td class="muted">${i.coverage_days}</td>
      <td class="${i.gaps ? 'cell-yellow' : 'muted'}">${i.gaps}</td><td class="muted">${i.duplicates}</td><td class="${i.malformed ? 'cell-red' : 'muted'}">${i.malformed}</td>
      <td><span class="badge ${i.clean ? 'badge-green' : 'badge-yellow'}">${i.clean ? t('q_clean_badge') : t('q_issue_badge')}</span></td></tr>`).join('');
    table.innerHTML = `<table><thead><tr><th>${t('q_col_dataset')}</th><th>${t('q_col_rows')}</th><th>${t('q_col_coverage')}</th><th>${t('q_col_gaps')}</th><th>${t('q_col_dupes')}</th><th>${t('q_col_malformed')}</th><th>${t('q_col_status')}</th></tr></thead><tbody>${rows}</tbody></table>`;
  });
  // forward-test
  const fwd = document.getElementById('forward-test-body');
  fwd.innerHTML = `<div class="empty-state" style="padding:16px"><span class="spinner"></span></div>`;
  fetch('/api/forward-test').then(r => r.json()).then(d => {
    if (!d.rows || !d.rows.length) { fwd.innerHTML = `<p class="muted">${t('fwd_no_data')}</p>`; return; }
    const statusBadge = s => ({ ok: 'badge-green', diverging: 'badge-red', no_trades: 'badge-gray' }[s] || 'badge-gray');
    const statusTxt = s => ({ ok: t('fwd_status_ok'), diverging: t('fwd_status_diverging'), no_trades: t('fwd_status_no_trades') }[s] || s);
    const rows = d.rows.map(r => `<tr><td><b>${esc(r.symbol)}</b></td>
      <td class="muted">${r.expected_return != null ? fmtPct(r.expected_return) : '—'}</td>
      <td class="${r.realized_return >= 0 ? 'pos' : 'neg'}">${r.realized_return != null ? fmtPct(r.realized_return) : '—'}</td>
      <td class="muted">${r.trades || 0}</td>
      <td class="${(r.divergence || 0) < 0 ? 'neg' : 'pos'}">${r.divergence != null ? fmtPct(r.divergence) : '—'}</td>
      <td><span class="badge ${statusBadge(r.status)}">${statusTxt(r.status)}</span></td></tr>`).join('');
    fwd.innerHTML = `<div class="table-wrap"><table><thead><tr><th>${t('fwd_col_symbol')}</th><th>${t('fwd_col_expected')}</th><th>${t('fwd_col_realized')}</th><th>${t('fwd_col_trades')}</th><th>${t('fwd_col_divergence')}</th><th>${t('fwd_col_status')}</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${d.alerts && d.alerts.length ? '' : `<div class="note">${t('fwd_no_alerts')} · ${d.total_closed_trades} trades</div>`}`;
  });
}

// ═══════════════════════════════════════════════════════════════ EXECUTION STYLE
function setExecStyle(style, btn) {
  state.executionStyle = style;
  btn.parentElement.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

// ═══════════════════════════════════════════════════════════════ FLEET RISK
const fmtUsd = x => (x == null ? '—' : '$' + Number(x).toLocaleString('en-US', { maximumFractionDigits: 0 }));

async function loadFleetRisk() {
  const metrics = document.getElementById('fleet-metrics');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  let d;
  try { d = await (await fetch('/api/fleet-risk')).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  state.fleet = d;

  document.getElementById('fleet-generated').textContent =
    d.generated_at ? fmtDateTime(d.generated_at) : '';

  // alerts + sidebar badge
  const alertsEl = document.getElementById('fleet-alerts');
  const badge = document.getElementById('fleet-alert-badge');
  const alerts = d.alerts || [];
  if (badge) {
    badge.style.display = alerts.length ? '' : 'none';
    badge.textContent = alerts.length;
  }
  if (!alerts.length) {
    alertsEl.innerHTML = `<div class="ok" style="margin-bottom:16px">✓ ${t('fleet_ok')}</div>`;
  } else {
    alertsEl.innerHTML = alerts.map(a => {
      const msg = t('fleet_alert_' + a.code, { value: a.value == null ? '—' : a.value, limit: a.limit, context: esc(a.context || '') });
      const crit = a.level === 'critical';
      return `<div class="alert" style="${crit ? 'border-color:rgba(248,113,113,.5);background:rgba(248,113,113,.08)' : ''}">
        <b style="color:${crit ? 'var(--red)' : 'var(--yellow)'}">${crit ? '⛔' : '⚠'}</b> ${msg}</div>`;
    }).join('');
  }

  const f = d.fleet || {};
  if (!d.positions || !Object.keys(f).length) {
    metrics.innerHTML = `<p class="muted" style="grid-column:1/-1">${t('fleet_empty')}</p>`;
    return;
  }
  const mc = (label, val, cls) =>
    `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}">${val}</div></div>`;
  metrics.innerHTML =
    mc(t('fleet_m_equity'), fmtUsd(f.equity_usd)) +
    mc(t('fleet_m_gross'), fmtUsd(f.gross_notional)) +
    mc(t('fleet_m_net'), fmtUsd(f.net_notional), f.net_notional >= 0 ? 'pos' : 'neg') +
    mc(t('fleet_m_lev'), (f.gross_leverage ?? 0) + 'x') +
    mc(t('fleet_m_delta'), fmtUsd(f.net_beta_delta) + (f.net_beta_delta_pct != null ? ` <span style="font-size:12px;color:var(--text3)">(${f.net_beta_delta_pct}%)</span>` : ''), f.net_beta_delta >= 0 ? 'pos' : 'neg') +
    mc(t('fleet_m_hhi'), f.hhi ?? '—') +
    mc(t('fleet_m_npos'), f.n_positions ?? 0) +
    mc(t('fleet_m_corr'), f.avg_pairwise_corr ?? '—');

  renderFleetExposureChart(d);
  renderFleetCorrChart(d);
  renderFleetBotTable(d);
  renderFleetPosTable(d);
}

function renderFleetExposureChart(d) {
  const assets = (d.per_asset || []).slice(0, 20).reverse();
  const el = document.getElementById('chart-fleet-exposure');
  if (!assets.length) { el.innerHTML = `<div class="empty-state"><p>${t('fleet_empty')}</p></div>`; return; }
  Plotly.newPlot(el, [{
    type: 'bar', orientation: 'h',
    y: assets.map(a => a.base),
    x: assets.map(a => a.beta_delta),
    marker: { color: assets.map(a => a.beta_delta >= 0 ? '#34d399' : '#f87171') },
    customdata: assets.map(a => [a.gross_notional, a.beta_btc ?? '—', a.bots.join(', ')]),
    hovertemplate: '<b>%{y}</b><br>βΔ: %{x:$,.0f}<br>gross: %{customdata[0]:$,.0f}<br>β: %{customdata[1]}<br>%{customdata[2]}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 60, r: 20, t: 10, b: 40 },
    xaxis: { gridcolor: GRID, zerolinecolor: '#3a4761' }, yaxis: { gridcolor: GRID },
  }, { displayModeBar: false, responsive: true });
}

function renderFleetCorrChart(d) {
  const c = d.correlation || {};
  const el = document.getElementById('chart-fleet-corr');
  if (!c.bases || c.bases.length < 2 || !c.matrix.length) {
    el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return;
  }
  Plotly.newPlot(el, [{
    type: 'heatmap', x: c.bases, y: c.bases, z: c.matrix,
    zmin: -1, zmax: 1, colorscale: [[0, '#f87171'], [0.5, '#11151f'], [1, '#2dd4bf']],
    hovertemplate: '%{y} × %{x}: %{z}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 60, r: 20, t: 10, b: 50 },
  }, { displayModeBar: false, responsive: true });
}

function renderFleetBotTable(d) {
  const rows = (d.per_bot || []).map(b => `<tr>
    <td><b>${esc(b.bot)}</b>${b.db_found ? '' : ' <span class="badge badge-red">DB?</span>'}</td>
    <td>${fmtUsd(b.equity_usd)}</td>
    <td class="${b.realized_pnl >= 0 ? 'pos' : 'neg'}">${fmtUsd(b.realized_pnl)}</td>
    <td class="${(b.unrealized_pnl || 0) >= 0 ? 'pos' : 'neg'}">${fmtUsd(b.unrealized_pnl)}</td>
    <td>${fmtUsd(b.gross_notional)}</td>
    <td>${b.gross_leverage != null ? b.gross_leverage + 'x' : '—'}</td>
    <td>${b.n_open}</td></tr>`).join('');
  document.getElementById('fleet-bot-table').innerHTML =
    `<table><thead><tr><th>${t('fleet_h_bot')}</th><th>${t('fleet_h_equity')}</th><th>${t('fleet_h_realized')}</th><th>${t('fleet_h_upnl')}</th><th>${t('fleet_h_gross')}</th><th>${t('fleet_h_lev')}</th><th>${t('fleet_h_open')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderFleetPosTable(d) {
  const betas = {};
  (d.per_asset || []).forEach(a => { betas[a.base] = a.beta_btc; });
  const rows = (d.positions || []).map(p => `<tr>
    <td class="muted">${esc(p.bot)}</td>
    <td><b>${esc(p.pair)}</b></td>
    <td><span class="pill ${p.side}">${p.side}</span></td>
    <td>${p.leverage}x</td>
    <td>${fmtUsd(p.stake_usd)}</td>
    <td>${fmtUsd(p.notional_usd)}</td>
    <td class="${(p.unrealized_pnl || 0) >= 0 ? 'pos' : 'neg'}">${p.unrealized_pnl != null ? fmtUsd(p.unrealized_pnl) : '—'}</td>
    <td>${betas[p.base] ?? '—'}</td>
    <td class="muted">${p.price_age_hours != null ? p.price_age_hours + 'h' : '—'}${p.price_stale ? ` <span class="badge badge-yellow">${t('fleet_stale')}</span>` : ''}</td>
  </tr>`).join('');
  document.getElementById('fleet-pos-table').innerHTML =
    `<table><thead><tr><th>${t('fleet_h_bot')}</th><th>${t('fleet_h_pair')}</th><th>${t('fleet_h_side')}</th><th>${t('fleet_h_lev')}</th><th>${t('fleet_h_stake')}</th><th>${t('fleet_h_notional')}</th><th>${t('fleet_h_upnl')}</th><th>${t('fleet_h_beta')}</th><th>${t('fleet_h_age')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ═══════════════════════════════════════════════════════════════ CAPACITY
async function loadCapacity(refresh = false) {
  const metrics = document.getElementById('cap-metrics');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  let d;
  try { d = await (await fetch('/api/capacity' + (refresh ? '?refresh=1' : ''))).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  state.capacity = d;
  document.getElementById('cap-generated').textContent = d.generated_at ? fmtDateTime(d.generated_at) : '';

  const edges = d.edges || [];
  if (!edges.length) {
    metrics.innerHTML = `<p class="muted" style="grid-column:1/-1">${t('cap_empty')}</p>`;
    document.getElementById('cap-table').innerHTML = '';
    return;
  }
  const caps = edges.map(e => e.capacity_notional || 0);
  const utils = edges.filter(e => e.utilization_pct != null).map(e => e.utilization_pct);
  const zeroCap = edges.filter(e => !e.capacity_notional).length;
  const median = arr => { const s = [...arr].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
  const mc = (label, val, cls) => `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}" style="font-size:19px">${val}</div></div>`;
  metrics.innerHTML =
    mc(t('cap_m_edges'), edges.length) +
    mc(t('cap_m_books'), d.n_books || 0) +
    mc(t('cap_m_median'), fmtUsd(median(caps))) +
    mc(t('cap_m_zero'), zeroCap, zeroCap ? 'neg' : 'pos') +
    mc(t('cap_m_maxutil'), utils.length ? Math.max(...utils) + '%' : '—',
      utils.length && Math.max(...utils) > 50 ? 'neg' : 'pos');

  // symbol selector
  const sel = document.getElementById('cap-symbol-select');
  sel.innerHTML = edges.map((e, i) =>
    `<option value="${i}">${esc(e.symbol)} · ${esc(e.strategy)}</option>`).join('');
  renderCapacityCurve();
  renderCapacityTable(edges);
}

function renderCapacityCurve() {
  const d = state.capacity; if (!d || !d.edges || !d.edges.length) return;
  const i = parseInt(document.getElementById('cap-symbol-select').value || '0', 10);
  const e = d.edges[i] || d.edges[0];
  const el = document.getElementById('chart-capacity-curve');
  const xs = e.curve.map(p => p.notional);
  Plotly.newPlot(el, [
    { x: xs, y: e.curve.map(p => p.net_edge_bps), name: t('cap_net_edge'),
      mode: 'lines+markers', line: { color: '#2dd4bf', width: 2.5 } },
    { x: xs, y: e.curve.map(p => p.impact_rt_bps), name: t('cap_impact'),
      mode: 'lines', line: { color: '#f87171', dash: 'dot' } },
  ], {
    ...PLOTLY_DARK, margin: { l: 55, r: 20, t: 12, b: 45 },
    xaxis: { type: 'log', title: { text: 'USD', font: { size: 11 } }, gridcolor: GRID },
    yaxis: { title: { text: 'bps', font: { size: 11 } }, gridcolor: GRID, zerolinecolor: '#3a4761', zerolinewidth: 2 },
    legend: { orientation: 'h', y: 1.12 },
    shapes: e.capacity_notional ? [{ type: 'line', x0: e.capacity_notional, x1: e.capacity_notional, y0: 0, y1: 1, yref: 'paper', line: { color: '#fbbf24', dash: 'dash' } }] : [],
    annotations: e.capacity_notional ? [{ x: Math.log10(e.capacity_notional), y: 1, yref: 'paper', text: t('cap_capacity_line'), showarrow: false, font: { color: '#fbbf24', size: 11 }, yanchor: 'bottom' }] : [],
  }, { displayModeBar: false, responsive: true });
}

function renderCapacityTable(edges) {
  const rows = edges.map(e => {
    const utilCls = e.utilization_pct == null ? 'muted' : e.utilization_pct > 50 ? 'neg' : e.utilization_pct > 25 ? 'cell-yellow' : 'pos';
    return `<tr>
      <td><b>${esc(e.symbol)}</b> ${e.deployable ? '<span class="badge badge-green">live</span>' : ''}</td>
      <td class="muted">${esc(e.strategy)}</td>
      <td>${e.edge_rt_bps} bps</td>
      <td>${e.adv_usd ? fmtUsd(e.adv_usd) : '—'}</td>
      <td>${e.k_l2 ?? '—'}</td>
      <td class="${e.capacity_notional ? '' : 'neg'}">${e.capacity_notional ? fmtUsd(e.capacity_notional) : '0'}</td>
      <td>${e.half_edge_notional ? fmtUsd(e.half_edge_notional) : '—'}</td>
      <td>${e.current_order_usd ? fmtUsd(e.current_order_usd) : '—'}</td>
      <td class="${utilCls}">${e.utilization_pct != null ? e.utilization_pct + '%' : '—'}</td></tr>`;
  }).join('');
  document.getElementById('cap-table').innerHTML =
    `<table><thead><tr><th>${t('symbol_label')}</th><th>${t('edges_strategy')}</th><th>${t('cap_h_edge')}</th><th>ADV</th><th>k(L2)</th><th>${t('cap_h_capacity')}</th><th>${t('cap_h_half')}</th><th>${t('cap_h_current')}</th><th>${t('cap_h_util')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ═══════════════════════════════════════════════════════════════ STRESS
const stressLabel = s => (LANG === 'fa' ? s.label_fa : s.label_en) || s.key;
const VERDICT_BADGE = { ok: 'badge-green', hit: 'badge-yellow', critical: 'badge-red', wiped: 'badge-red' };

async function loadStress() {
  const metrics = document.getElementById('stress-metrics');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  let d;
  try { d = await (await fetch('/api/stress')).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  state.stress = d;
  document.getElementById('stress-generated').textContent = d.generated_at ? fmtDateTime(d.generated_at) : '';

  const scns = d.scenarios || [];
  if (!scns.length) {
    metrics.innerHTML = `<p class="muted" style="grid-column:1/-1">${t('stress_empty')}</p>`;
    return;
  }
  const worst = scns[0];
  const totalLiq = Math.max(...scns.map(s => s.n_liquidations));
  const mc = (label, val, cls) => `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}" style="font-size:19px">${val}</div></div>`;
  metrics.innerHTML =
    mc(t('stress_m_equity'), fmtUsd(d.equity_usd)) +
    mc(t('stress_m_positions'), d.n_positions) +
    mc(t('stress_m_worst'), stressLabel(worst), 'neg') +
    mc(t('stress_m_worst_pnl'), fmtUsd(worst.fleet_pnl_usd) + (worst.fleet_pnl_pct != null ? ` (${worst.fleet_pnl_pct}%)` : ''), 'neg') +
    mc(t('stress_m_liq'), totalLiq, totalLiq ? 'neg' : 'pos');

  // bar chart of pnl% per scenario
  const ordered = [...scns].reverse();
  Plotly.newPlot(document.getElementById('chart-stress'), [{
    type: 'bar', orientation: 'h',
    y: ordered.map(stressLabel),
    x: ordered.map(s => s.fleet_pnl_pct),
    marker: { color: ordered.map(s => s.fleet_pnl_pct >= 0 ? '#34d399' : s.fleet_pnl_pct <= -30 ? '#f87171' : s.fleet_pnl_pct <= -10 ? '#fb923c' : '#fbbf24') },
    customdata: ordered.map(s => [fmtUsd(s.fleet_pnl_usd), s.n_liquidations]),
    hovertemplate: '<b>%{y}</b><br>%{x}% · %{customdata[0]}<br>liq: %{customdata[1]}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 170, r: 20, t: 10, b: 40 },
    xaxis: { gridcolor: GRID, zerolinecolor: '#3a4761', ticksuffix: '%' }, yaxis: { gridcolor: GRID },
  }, { displayModeBar: false, responsive: true });

  // historical path selector
  const hist = scns.filter(s => s.btc_path);
  const sel = document.getElementById('stress-path-select');
  sel.innerHTML = hist.length
    ? hist.map(s => `<option value="${s.key}">${stressLabel(s)}</option>`).join('')
    : `<option value="">—</option>`;
  renderStressPath();
  renderStressTable(scns);
}

function renderStressPath() {
  const d = state.stress; if (!d) return;
  const key = document.getElementById('stress-path-select').value;
  const s = (d.scenarios || []).find(x => x.key === key && x.btc_path);
  const el = document.getElementById('chart-stress-path');
  if (!s) { el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return; }
  Plotly.newPlot(el, [{
    x: s.btc_path.dates, y: s.btc_path.returns.map(r => r * 100),
    mode: 'lines+markers', fill: 'tozeroy',
    line: { color: '#f87171', width: 2.5 }, fillcolor: 'rgba(248,113,113,.12)',
    hovertemplate: '%{x}: %{y:.1f}%<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 50, r: 20, t: 12, b: 45 },
    xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID, ticksuffix: '%', zerolinecolor: '#3a4761' },
  }, { displayModeBar: false, responsive: true });
}

function renderStressTable(scns) {
  const rows = scns.map(s => {
    const worstPos = (s.worst_positions || [])[0];
    return `<tr>
      <td><b>${stressLabel(s)}</b>${s.data_available === false ? ` <span class="badge badge-gray" title="${t('stress_fallback')}">≈</span>` : ''}</td>
      <td class="${s.market_move >= 0 ? 'pos' : 'neg'}">${(s.market_move * 100).toFixed(1)}%</td>
      <td class="${s.fleet_pnl_usd >= 0 ? 'pos' : 'neg'}">${fmtUsd(s.fleet_pnl_usd)} <span class="muted">(${s.fleet_pnl_pct ?? '—'}%)</span></td>
      <td>${fmtUsd(s.exit_cost_usd)}</td>
      <td class="${s.n_liquidations ? 'neg' : ''}">${s.n_liquidations}</td>
      <td>${fmtUsd(s.equity_after)}</td>
      <td class="muted" style="font-size:11px">${worstPos ? esc(worstPos.bot + ' · ' + worstPos.pair) + ' (' + fmtUsd(worstPos.pnl) + (worstPos.liquidated ? ' ⚠' : '') + ')' : '—'}</td>
      <td><span class="badge ${VERDICT_BADGE[s.verdict] || 'badge-gray'}">${t('stress_v_' + s.verdict)}</span></td></tr>`;
  }).join('');
  document.getElementById('stress-table').innerHTML =
    `<table><thead><tr><th>${t('stress_h_scenario')}</th><th>${t('stress_h_move')}</th><th>${t('stress_h_pnl')}</th><th>${t('stress_h_exit')}</th><th>${t('stress_h_liq')}</th><th>${t('stress_h_after')}</th><th>${t('stress_h_worst_pos')}</th><th>${t('stress_h_verdict')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ═══════════════════════════════════════════════════════════════ TRIAL LEDGER
async function loadTrials() {
  const metrics = document.getElementById('trials-metrics');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  let d;
  try { d = await (await fetch('/api/trials')).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  state.trials = d;

  const s = d.stats || {};
  const mc = (label, val, cls) => `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}" style="font-size:20px">${val}</div></div>`;
  const passShare = s.n_unique ? (100 * s.n_ever_passed / s.n_unique).toFixed(1) + '%' : '—';
  metrics.innerHTML =
    mc(t('trials_m_unique'), (s.n_unique || 0).toLocaleString()) +
    mc(t('trials_m_runs'), (s.n_runs_total || 0).toLocaleString()) +
    mc(t('trials_m_tonight'), d.n_scanned_tonight != null ? d.n_scanned_tonight.toLocaleString() : '—') +
    mc(t('trials_m_passed'), (s.n_ever_passed || 0).toLocaleString() + ` <span style="font-size:12px;color:var(--text3)">(${passShare})</span>`) +
    mc(t('trials_m_srvar'), s.sr_variance != null ? Number(s.sr_variance).toExponential(2) : '—');
  if (!s.n_unique) {
    metrics.innerHTML += `<div class="metric-card" style="grid-column:1/-1"><div class="lbl">ℹ</div><div style="font-size:12px;color:var(--text2);margin-top:4px">${t('trials_empty')}</div></div>`;
  }

  // timeline
  const tl = d.timeline || [];
  const tlEl = document.getElementById('chart-trials-timeline');
  if (tl.length) {
    Plotly.newPlot(tlEl, [
      { x: tl.map(p => p.date), y: tl.map(p => p.cumulative), name: t('trials_cumulative'),
        mode: 'lines', fill: 'tozeroy', line: { color: '#818cf8', width: 2.5 }, fillcolor: 'rgba(129,140,248,.12)' },
      { x: tl.map(p => p.date), y: tl.map(p => p.new), name: t('trials_new'), type: 'bar',
        marker: { color: '#2dd4bf' }, yaxis: 'y2' },
    ], {
      ...PLOTLY_DARK, margin: { l: 55, r: 45, t: 12, b: 45 },
      xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID },
      yaxis2: { overlaying: 'y', side: 'right', gridcolor: 'transparent' },
      legend: { orientation: 'h', y: 1.12 },
    }, { displayModeBar: false, responsive: true });
  } else {
    tlEl.innerHTML = `<div class="empty-state"><p>${t('trials_empty_short')}</p></div>`;
  }

  // strategy breakdown
  const st = d.strategies || [];
  document.getElementById('trials-strat-table').innerHTML = st.length ? `<table>
    <thead><tr><th>${t('edges_strategy')}</th><th>${t('trials_h_hyps')}</th><th>${t('trials_h_passed')}</th><th>${t('trials_h_passrate')}</th><th>${t('trials_h_bestsr')}</th></tr></thead>
    <tbody>${st.map(r => `<tr><td><b>${esc(strategyLabel(r.strategy))}</b></td>
      <td>${r.n_hypotheses}</td><td>${r.n_ever_passed}</td>
      <td class="${r.pass_rate > 0.1 ? 'pos' : 'muted'}">${(r.pass_rate * 100).toFixed(1)}%</td>
      <td>${r.best_sr_pb}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted" style="padding:16px">${t('trials_empty_short')}</p>`;

  // top edges: nightly vs cumulative DSR
  const top = d.top_edges || [];
  const dsrCls = v => v == null ? 'muted' : v >= 0.95 ? 'pos' : v >= 0.5 ? 'cell-yellow' : 'neg';
  document.getElementById('trials-top-table').innerHTML = top.length ? `<table>
    <thead><tr><th>${t('symbol_label')}</th><th>${t('edges_strategy')}</th><th>${t('timeframe')}</th><th>OOS Sharpe</th><th>${t('trials_h_dsr_night')}</th><th>${t('trials_h_dsr_cum')}</th><th>${t('trials_h_verdict')}</th></tr></thead>
    <tbody>${top.map(e => {
      const demoted = e.dsr != null && e.dsr_cum != null && e.dsr >= 0.95 && e.dsr_cum < 0.95;
      return `<tr><td><b>${esc(e.symbol)}</b> ${e.deployable ? '<span class="badge badge-green">live</span>' : ''}</td>
      <td class="muted">${esc(strategyLabel(e.strategy))}</td><td><span class="tf-badge">${esc(e.timeframe || '—')}</span></td>
      <td>${e.oos_sharpe ?? '—'}</td>
      <td class="${dsrCls(e.dsr)}">${e.dsr ?? '—'}</td>
      <td class="${dsrCls(e.dsr_cum)}">${e.dsr_cum ?? '—'}</td>
      <td>${demoted ? `<span class="badge badge-red">${t('trials_demoted')}</span>` : e.dsr_cum != null && e.dsr_cum >= 0.95 ? `<span class="badge badge-green">${t('trials_survives')}</span>` : `<span class="badge badge-gray">—</span>`}</td></tr>`;
    }).join('')}</tbody></table>`
    : `<p class="muted" style="padding:16px">${t('trials_empty_short')}</p>`;
}

// ═══════════════════════════════════════════════════════════════ ATTRIBUTION
async function loadAttribution(refresh = false) {
  const metrics = document.getElementById('attr-metrics');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  const days = document.getElementById('attr-days').value;
  let d;
  try { d = await (await fetch(`/api/attribution?days=${days}${refresh ? '&refresh=1' : ''}`)).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  state.attribution = d;

  const tt = d.totals || {};
  const mc = (label, val, cls) => `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}" style="font-size:19px">${val}</div></div>`;
  const money = (v, invert) => v == null ? '—' : fmtUsd(invert ? -v : v);
  const clsOf = (v, invert) => v == null ? '' : ((invert ? -v : v) >= 0 ? 'pos' : 'neg');
  metrics.innerHTML =
    mc(t('attr_m_intended'), money(tt.intended), clsOf(tt.intended)) +
    mc(t('attr_m_slip'), money((tt.entry_slip || 0) + (tt.exit_slip || 0), true), clsOf((tt.entry_slip || 0) + (tt.exit_slip || 0), true)) +
    mc(t('attr_m_fees'), money(tt.fees, true), 'neg') +
    mc(t('attr_m_funding'), money(tt.funding), clsOf(tt.funding)) +
    mc(t('attr_m_net'), money(tt.net), clsOf(tt.net)) +
    mc(t('attr_m_residual'), money(tt.residual), 'muted');

  const bots = (d.per_bot || []).filter(b => b.n_trades);
  const sel = document.getElementById('attr-bot-select');
  sel.innerHTML = `<option value="__fleet__">${t('attr_fleet')}</option>` +
    bots.map(b => `<option value="${esc(b.bot)}">${esc(b.bot)}</option>`).join('');
  renderAttrWaterfall();
  renderAttrCapture(bots);
  renderAttrBotTable(bots);
}

function renderAttrWaterfall() {
  const d = state.attribution; if (!d) return;
  const key = document.getElementById('attr-bot-select').value;
  const bots = (d.per_bot || []).filter(b => b.n_trades);
  const c = key === '__fleet__' ? d.totals : (bots.find(b => b.bot === key) || {}).components;
  const el = document.getElementById('chart-attr-waterfall');
  if (!c) { el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return; }
  Plotly.newPlot(el, [{
    type: 'waterfall', orientation: 'v',
    measure: ['relative', 'relative', 'relative', 'relative', 'relative', 'relative', 'total'],
    x: [t('attr_m_intended'), t('attr_w_entry_slip'), t('attr_w_exit_slip'), t('attr_m_fees'), t('attr_m_funding'), t('attr_m_residual'), t('attr_m_net')],
    y: [c.intended, -(c.entry_slip || 0), -(c.exit_slip || 0), -(c.fees || 0), c.funding || 0, c.residual || 0, 0],
    connector: { line: { color: '#2f3b57' } },
    increasing: { marker: { color: '#34d399' } },
    decreasing: { marker: { color: '#f87171' } },
    totals: { marker: { color: '#818cf8' } },
    hovertemplate: '%{x}: %{y:$,.2f}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 55, r: 20, t: 12, b: 70 },
    yaxis: { gridcolor: GRID, zerolinecolor: '#3a4761' }, xaxis: { tickangle: -30 },
  }, { displayModeBar: false, responsive: true });
  renderAttrReasonTable();
}

function renderAttrCapture(bots) {
  const el = document.getElementById('chart-attr-capture');
  const withCap = bots.filter(b => b.mfe_capture_mean != null);
  if (!withCap.length) { el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return; }
  Plotly.newPlot(el, [{
    type: 'bar',
    x: withCap.map(b => b.bot),
    y: withCap.map(b => b.mfe_capture_mean),
    marker: { color: withCap.map(b => b.mfe_capture_mean >= 0.3 ? '#34d399' : b.mfe_capture_mean >= 0 ? '#fbbf24' : '#f87171') },
    customdata: withCap.map(b => [b.mfe_mean_pct, b.n_capture_measured]),
    hovertemplate: '<b>%{x}</b><br>capture: %{y}<br>MFE μ: %{customdata[0]}%<br>n: %{customdata[1]}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 50, r: 20, t: 12, b: 45 },
    yaxis: { gridcolor: GRID, zerolinecolor: '#3a4761', title: { text: 'MFE capture', font: { size: 11 } } },
  }, { displayModeBar: false, responsive: true });
}

function renderAttrBotTable(bots) {
  const rows = bots.map(b => {
    const c = b.components || {};
    const slip = (c.entry_slip || 0) + (c.exit_slip || 0);
    return `<tr><td><b>${esc(b.bot)}</b></td><td>${b.n_trades}</td>
      <td class="${c.intended >= 0 ? 'pos' : 'neg'}">${fmtUsd(c.intended)}</td>
      <td class="${slip <= 0 ? 'pos' : 'neg'}">${fmtUsd(-slip)}</td>
      <td class="neg">${fmtUsd(-(c.fees || 0))}</td>
      <td class="${(c.funding || 0) >= 0 ? 'pos' : 'neg'}">${fmtUsd(c.funding)}</td>
      <td class="${c.net >= 0 ? 'pos' : 'neg'}"><b>${fmtUsd(c.net)}</b></td>
      <td class="${b.mfe_capture_mean == null ? 'muted' : b.mfe_capture_mean >= 0.3 ? 'pos' : 'neg'}">${b.mfe_capture_mean ?? '—'}</td>
      <td class="muted">${b.mae_mean_pct != null ? b.mae_mean_pct + '%' : '—'}</td></tr>`;
  }).join('');
  document.getElementById('attr-bot-table').innerHTML =
    `<table><thead><tr><th>${t('fleet_h_bot')}</th><th>${t('attr_h_trades')}</th><th>${t('attr_m_intended')}</th><th>${t('attr_m_slip')}</th><th>${t('attr_m_fees')}</th><th>${t('attr_m_funding')}</th><th>${t('attr_m_net')}</th><th>MFE-cap</th><th>MAE μ</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderAttrReasonTable() {
  const d = state.attribution; if (!d) return;
  const key = document.getElementById('attr-bot-select').value;
  const el = document.getElementById('attr-reason-table');
  const bots = (d.per_bot || []).filter(b => b.n_trades);
  let reasons;
  if (key === '__fleet__') {
    const merged = {};
    bots.forEach(b => (b.by_exit_reason || []).forEach(r => {
      const m = merged[r.exit_reason] || (merged[r.exit_reason] = { exit_reason: r.exit_reason, n: 0, net: 0, intended: 0 });
      m.n += r.n; m.net += r.net; m.intended += r.intended;
    }));
    reasons = Object.values(merged).sort((a, b) => a.net - b.net);
  } else {
    reasons = (bots.find(b => b.bot === key) || {}).by_exit_reason || [];
  }
  el.innerHTML = reasons.length ? `<table>
    <thead><tr><th>${t('attr_h_reason')}</th><th>${t('attr_h_trades')}</th><th>${t('attr_m_intended')}</th><th>${t('attr_m_net')}</th></tr></thead>
    <tbody>${reasons.map(r => `<tr><td><b>${esc(r.exit_reason)}</b></td><td>${r.n}</td>
      <td class="${r.intended >= 0 ? 'pos' : 'neg'}">${fmtUsd(r.intended)}</td>
      <td class="${r.net >= 0 ? 'pos' : 'neg'}">${fmtUsd(r.net)}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted" style="padding:16px">—</p>`;
}

// ═══════════════════════════════════════════════════════════════ PIPELINE HEALTH
const PIPE_STATUS = {
  ok: { color: 'var(--green)', badge: 'badge-green' },
  late: { color: 'var(--yellow)', badge: 'badge-yellow' },
  missing: { color: 'var(--red)', badge: 'badge-red' },
};

async function loadPipeline() {
  const grid = document.getElementById('pipe-grid');
  grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  let d;
  try { d = await (await fetch('/api/pipeline-health')).json(); }
  catch (e) { grid.innerHTML = `<p class="neg">${esc(e.message)}</p>`; return; }
  document.getElementById('pipe-generated').textContent = d.generated_at ? fmtDateTime(d.generated_at) : '';

  const c = d.counts || {};
  const failing = (c.late || 0) + (c.missing || 0);
  const badge = document.getElementById('pipeline-alert-badge');
  if (badge) { badge.style.display = failing ? '' : 'none'; badge.textContent = failing; }

  const banner = document.getElementById('pipe-banner');
  if (d.healthy) {
    banner.innerHTML = `<div class="ok" style="margin-bottom:16px">✓ ${t('pipe_all_ok', { n: d.n_jobs })}</div>`;
  } else {
    const crit = (d.critical_failing || []).join(', ');
    banner.innerHTML = `<div class="alert" style="border-color:rgba(248,113,113,.5);background:rgba(248,113,113,.08);margin-bottom:16px">
      ⛔ ${t('pipe_failing', { late: c.late || 0, missing: c.missing || 0 })}${crit ? ` — <b>${esc(crit)}</b>` : ''}</div>`;
  }

  grid.innerHTML = (d.jobs || []).map(j => {
    const s = PIPE_STATUS[j.status] || PIPE_STATUS.missing;
    const desc = LANG === 'fa' ? j.desc_fa : j.desc_en;
    return `<div class="inv-card" style="cursor:default;border-inline-start:3px solid ${s.color}">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div class="exch">${esc(j.name)}</div>
        <span class="badge ${s.badge}">${t('pipe_s_' + j.status)}</span>
      </div>
      <div style="font-size:12px;color:var(--text2);margin-top:6px;min-height:32px">${esc(desc || '')}</div>
      <div class="dates" style="display:flex;justify-content:space-between">
        <span>${t('pipe_age')}: <b style="color:${s.color}">${j.age_hours != null ? j.age_hours + 'h' : '—'}</b> / ${j.max_age_hours}h</span>
        <span>${j.severity === 'critical' ? '🔴' : '🟡'}</span>
      </div>
      <div class="rows" style="direction:ltr;text-align:end;opacity:.7">${esc(j.artifact)}</div>
    </div>`;
  }).join('');

  const h = d.history || [];
  const el = document.getElementById('chart-pipe-history');
  if (h.length > 1) {
    Plotly.newPlot(el, [
      { x: h.map(p => p.ts), y: h.map(p => p.ok), name: 'ok', stackgroup: 'a', line: { color: '#34d399', width: 0.5 } },
      { x: h.map(p => p.ts), y: h.map(p => p.late), name: 'late', stackgroup: 'a', line: { color: '#fbbf24', width: 0.5 } },
      { x: h.map(p => p.ts), y: h.map(p => p.missing), name: 'missing', stackgroup: 'a', line: { color: '#f87171', width: 0.5 } },
    ], {
      ...PLOTLY_DARK, margin: { l: 40, r: 20, t: 12, b: 45 },
      xaxis: { gridcolor: GRID }, yaxis: { gridcolor: GRID },
      legend: { orientation: 'h', y: 1.15 },
    }, { displayModeBar: false, responsive: true });
  } else {
    el.innerHTML = `<div class="empty-state"><p>${t('pipe_history_empty')}</p></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════ ALT-DATA
async function loadAltdata(refresh = false) {
  const metrics = document.getElementById('alt-metrics');
  const btn = document.getElementById('alt-refresh-btn');
  metrics.innerHTML = `<div class="empty-state" style="grid-column:1/-1;padding:24px"><span class="spinner"></span></div>`;
  if (refresh && btn) { btn.disabled = true; }
  let d;
  try { d = await (await fetch('/api/altdata' + (refresh ? '?refresh=1' : ''))).json(); }
  catch (e) { metrics.innerHTML = `<p class="neg">${esc(e.message)}</p>`; if (btn) btn.disabled = false; return; }
  if (btn) btn.disabled = false;
  state.altdata = d;
  document.getElementById('alt-generated').textContent = d.generated_at ? fmtDateTime(d.generated_at) : '';

  // regime hints
  const hintsEl = document.getElementById('alt-hints');
  const hints = d.regime_hints || [];
  hintsEl.innerHTML = hints.length
    ? hints.map(h => `<div class="alert">💡 ${t('alt_hint_' + h)}</div>`).join('')
    : `<div class="ok" style="margin-bottom:16px">✓ ${t('alt_no_hints')}</div>`;

  const btc = (d.per_symbol || []).find(s => s.symbol === 'BTCUSDT') || {};
  const mc = (label, val, cls) => `<div class="metric-card"><div class="lbl">${label}</div><div class="val ${cls || ''}" style="font-size:19px">${val}</div></div>`;
  metrics.innerHTML =
    mc('DVOL BTC', d.dvol?.BTC ?? '—') +
    mc('DVOL ETH', d.dvol?.ETH ?? '—') +
    mc(t('alt_m_ls'), btc.ls_ratio ?? '—', btc.ls_ratio >= 3 ? 'neg' : '') +
    mc(t('alt_m_taker'), btc.taker_ratio ?? '—') +
    mc(t('alt_m_liq24'), fmtUsd(d.liquidations_24h_usd)) +
    mc(t('alt_m_perp_basis'), (() => {
      const p = (d.term_structure?.BTCUSDT || []).find(x => x.tenor === 'perp');
      return p ? p.basis_ann_pct + '%' : '—';
    })());

  // DVOL + L/S charts
  const line = (elId, series, color, name) => {
    const el = document.getElementById(elId);
    if (!series || !series.ts || !series.ts.length) { el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return; }
    Plotly.newPlot(el, [{ x: series.ts, y: series.values, name, mode: 'lines', fill: 'tozeroy',
      line: { color, width: 2 }, fillcolor: color.replace(')', ',.1)').replace('rgb', 'rgba') }], {
      ...PLOTLY_DARK, margin: { l: 45, r: 15, t: 10, b: 40 },
      xaxis: { gridcolor: GRID, nticks: 6 }, yaxis: { gridcolor: GRID },
    }, { displayModeBar: false, responsive: true });
  };
  line('chart-alt-dvol', d.dvol_series_btc, 'rgb(129,140,248)', 'DVOL');
  line('chart-alt-ls', d.ls_series_btc, 'rgb(45,212,191)', 'L/S');

  renderAltTerm();

  // funding extremes
  const ext = d.funding_extremes || [];
  document.getElementById('alt-extremes-table').innerHTML = ext.length ? `<table>
    <thead><tr><th>${t('symbol_label')}</th><th>${t('alt_h_funding_ann')}</th><th>${t('alt_h_premium')}</th></tr></thead>
    <tbody>${ext.map(r => `<tr><td><b>${esc(r.symbol)}</b></td>
      <td class="${Math.abs(r.funding_ann_pct) > 50 ? 'neg' : ''}">${r.funding_ann_pct}%</td>
      <td class="${r.premium_bps >= 0 ? 'pos' : 'neg'}">${r.premium_bps}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted" style="padding:16px">—</p>`;

  // liquidation tape
  const liq = d.recent_liquidations || [];
  document.getElementById('alt-liq-table').innerHTML = liq.length ? `<table>
    <thead><tr><th>${t('alt_h_time')}</th><th>${t('alt_h_side')}</th><th>${t('alt_h_notional')}</th></tr></thead>
    <tbody>${liq.map(r => `<tr><td class="muted" style="direction:ltr;text-align:end">${esc(String(r.ts).slice(0, 19))}</td>
      <td><span class="pill ${r.side === 'buy' ? 'short' : 'long'}">${r.side === 'buy' ? t('alt_shorts_liq') : t('alt_longs_liq')}</span></td>
      <td>${fmtUsd(r.notional_usd)}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted" style="padding:16px">—</p>`;
}

function renderAltTerm() {
  const d = state.altdata; if (!d) return;
  const key = document.getElementById('alt-term-select').value;
  const term = (d.term_structure || {})[key] || [];
  const el = document.getElementById('chart-alt-term');
  if (!term.length) { el.innerHTML = `<div class="empty-state"><p>—</p></div>`; return; }
  Plotly.newPlot(el, [{
    type: 'bar',
    x: term.map(x => x.tenor === 'perp' ? 'perp (funding)' : x.tenor),
    y: term.map(x => x.basis_ann_pct),
    marker: { color: term.map(x => x.basis_ann_pct >= 0 ? '#2dd4bf' : '#f87171') },
    customdata: term.map(x => [x.days, x.price]),
    hovertemplate: '<b>%{x}</b><br>%{y}% ann.<br>%{customdata[0]}d · $%{customdata[1]:,.0f}<extra></extra>',
  }], {
    ...PLOTLY_DARK, margin: { l: 45, r: 15, t: 10, b: 45 },
    yaxis: { gridcolor: GRID, ticksuffix: '%', zerolinecolor: '#3a4761' },
  }, { displayModeBar: false, responsive: true });
}

// ═══════════════════════════════════════════════════════════════ BOOT
document.addEventListener('DOMContentLoaded', init);
