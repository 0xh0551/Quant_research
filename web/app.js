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
async function loadDetailedInsight(file, symbol, exchange, tf) {
  document.getElementById('insights-step1').style.display = 'none';
  document.getElementById('insights-step2').style.display = '';
  document.getElementById('ins-det-title').textContent = `${symbol} · ${exchange.toUpperCase()} · ${tf}`;
  document.getElementById('insights-detail-loading').style.display = 'block';
  document.getElementById('insights-detail-content').style.display = 'none';
  try {
    const r = await fetch('/api/insights/detailed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file }) });
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
async function runLabBacktest() {
  if (!state.lab.dataset || !state.lab.strategy) return;
  const btn = document.getElementById('lab-run-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  document.getElementById('lab-results-empty').style.display = 'none';
  document.getElementById('lab-results-content').style.display = 'none';
  try {
    const r = await fetch('/api/lab/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: state.lab.dataset, strategy: state.lab.strategy, params: state.lab.params }) });
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
    const r = await fetch('/api/lab/optimize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: state.lab.dataset, strategy: state.lab.strategy }) });
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
      <div class="table-wrap"><table><thead><tr><th>${t('edges_col_exchange')}</th><th>${t('edges_col_symbol')}</th><th>${t('edges_col_tf')}</th><th>${t('edges_col_rule')}</th><th>${t('edges_col_dir')}</th><th>Sharpe</th><th>${t('edges_col_ci')}</th><th>${t('edges_col_psr')}</th><th>${t('edges_col_dsr')}</th><th>${t('edges_col_pbo')}</th><th>${t('edges_col_return_oos')}</th></tr></thead>
      <tbody>${top.slice(0, 20).map(c => {
        const dsr = c.dsr == null || c.dsr !== c.dsr ? '—' : fmtN(c.dsr, 2);
        const dsrCls = (c.deflated_pass) ? 'cell-green' : (c.dsr === c.dsr && c.dsr < 0.9 ? 'cell-red' : '');
        const ci = (c.sharpe_ci_low || c.sharpe_ci_high) ? `${fmtN(c.sharpe_ci_low, 1)}–${fmtN(c.sharpe_ci_high, 1)}` : '—';
        const pbo = c.pbo == null || c.pbo !== c.pbo ? '—' : (c.pbo * 100).toFixed(0) + '%';
        return `<tr><td class="muted">${esc(c.exchange)}</td><td><b>${esc(c.symbol)}</b></td><td>${esc(c.timeframe)}</td><td>${esc(c.strategy)}</td><td>${edgesDirPill(c.allow_short)}</td><td class="pos"><b>${fmtN(c.oos_sharpe)}</b></td><td class="muted" style="font-size:11px">${ci}</td><td>${c.psr != null ? (c.psr * 100).toFixed(0) + '%' : '—'}</td><td class="${dsrCls}">${dsr}</td><td class="muted">${pbo}</td><td class="${c.oos_total_return >= 0 ? 'pos' : 'neg'}">${fmtPct(c.oos_total_return)}</td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="note">${t('edges_rigor_hint')}</div></div>`;

  buildEdgeCharts(data);
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
  const bs = (d.basis || []).map(x => `<tr><td>${esc(x.spot)}</td><td>${esc(x.derivative)}</td><td class="${x.basis_now_pct >= 0 ? 'pos' : 'neg'}">${fmtN(x.basis_now_pct, 3)}%</td><td class="muted">${fmtN(x.basis_mean_pct, 3)}%</td><td class="muted">${fmtN(x.basis_std_pct, 3)}%</td></tr>`).join('');
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
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_spot')}</th><th>${t('cx_col_deriv')}</th><th>${t('cx_col_basis_now')}</th><th>${t('cx_col_basis_mean')}</th><th>${t('cx_col_basis_std')}</th></tr></thead><tbody>${bs || `<tr><td colspan="5" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div>
        <div class="note">${t('cx_basis_hint')}</div></div>
      <div class="card"><div class="card-title"><span class="dot"></span>${t('cx_liquidity')}</div>
        <div class="table-wrap"><table><thead><tr><th>${t('cx_col_venue')}</th><th>${t('cx_col_dvol')}</th></tr></thead><tbody>${liq || `<tr><td colspan="2" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div></div>
    </div>`;
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
  body.innerHTML = `
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_weights')} <span class="badge badge-cyan" style="margin-inline-start:8px">${d.method}</span></div><div id="pf-weights-chart" style="height:260px"></div></div>
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_metrics')}</div><div class="metric-grid">${metrics.map(([l, v, c]) => `<div class="metric-card"><div class="lbl">${l}</div><div class="val" style="font-size:18px;color:${c}">${v}</div></div>`).join('')}</div></div>
    <div class="card"><div class="card-title"><span class="dot"></span>${t('pf_sizing')}</div>
      <div class="table-wrap"><table><thead><tr><th>${t('pf_col_asset')}</th><th>${t('pf_col_weight')}</th><th>${t('pf_col_kelly')}</th><th>${t('pf_col_vol_lev')}</th></tr></thead><tbody>${sizingRows}</tbody></table></div></div>`;
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
    const rows = (d.recommendations || []).map((x, i) => {
      const w = Math.max(4, x.rl_score);
      return `<tr><td>${i + 1}</td><td class="muted">${esc(x.exchange)}</td><td><b>${esc(x.symbol)}</b></td>
        <td><div class="score-bar-bg" style="display:inline-block;width:90px;vertical-align:middle"><div class="score-bar-fill" style="width:${w}%;background:${x.rl_score >= 55 ? 'var(--green)' : x.rl_score >= 45 ? 'var(--cyan)' : 'var(--yellow)'}"></div></div> <b>${x.rl_score}</b></td>
        <td class="muted">${x.regime_changes}</td><td class="muted">${fmtN(x.reward_density, 2)}</td><td class="muted">${fmtN(x.low_predictability, 2)}</td></tr>`;
    }).join('');
    rlBody.innerHTML = `<div style="font-size:11px;color:var(--text3);margin-bottom:8px">${d.n_evaluated} ${t('mdl_rl_evaluated')}</div>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>${t('cx_col_venue')}</th><th>${t('edges_col_symbol')}</th><th>${t('mdl_rl_col_score')}</th><th>${t('mdl_rl_col_regimes')}</th><th>${t('mdl_rl_col_density')}</th><th>${t('mdl_rl_col_pred')}</th></tr></thead><tbody>${rows || `<tr><td colspan="7" class="muted">${t('no_data')}</td></tr>`}</tbody></table></div>`;
  }).catch(() => rlBody.innerHTML = `<p class="muted">${t('no_data')}</p>`);

  // ML eval dataset dropdown
  const sel = document.getElementById('ml-dataset');
  if (sel && !sel.options.length) {
    sel.innerHTML = state.inventory.map(i => `<option value="${i.file}">${i.symbol} · ${i.exchange} · ${i.timeframe}</option>`).join('');
  }
  loadExperiments();
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
    el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>${t('mdl_exp_col_name')}</th><th>${t('mdl_exp_col_metrics')}</th><th>${t('mdl_exp_col_seed')}</th><th>${t('mdl_exp_col_when')}</th></tr></thead>
      <tbody>${runs.map(r => `<tr><td>${esc(r.name)}</td><td class="muted" style="font-size:11px">${Object.entries(r.metrics || {}).map(([k, v]) => k + '=' + (typeof v === 'number' ? v.toFixed(3) : v)).join(', ')}</td><td class="muted">${r.seed ?? '—'}</td><td class="muted" style="font-size:11px">${fmtDateTime(r.ts * 1000)}</td></tr>`).join('')}</tbody></table></div>`;
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

// ═══════════════════════════════════════════════════════════════ BOOT
document.addEventListener('DOMContentLoaded', init);
