/* ============================================================================
 * Quant Research — home screen
 * ----------------------------------------------------------------------------
 * The platform used to navigate through one long sidebar list. This replaces it
 * with a launcher: every section is a tile, and every tile is a live widget —
 * its own KPIs, a micro-chart drawn as inline SVG, and controls that work
 * inside the card. One `/api/home/summary` call feeds all of them.
 *
 * Charts here are hand-rolled SVG on purpose: nineteen Plotly instances on the
 * landing view would cost more than the whole rest of the dashboard.
 * ========================================================================== */

/* Section glyphs — same marks as the old menu, reused by the tiles, the icon
   rail and the command palette so one section always looks like itself. */
const HOME_ICONS = {
  download:    '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  inventory:   '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  quality:     '<path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  research:    '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M11 8v6M8 11h6"/>',
  report:      '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  insights:    '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  lab:         '<path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"/>',
  edges:       '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  trials:      '<path d="M4 19.5A2.5 2.5 0 016.5 17H20M4 19.5A2.5 2.5 0 006.5 22H20V2H6.5A2.5 2.5 0 004 4.5z"/><path d="M9 7h7M9 11h7"/>',
  capacity:    '<path d="M3 20h18M5 20V9m4 11V5m4 15v-8m4 8V11m4 9v-5"/>',
  crossex:     '<path d="M7 16V4M7 4L3 8M7 4l4 4M17 8v12M17 20l4-4M17 20l-4-4"/>',
  fleet:       '<path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/><path d="M8 12l2.5 2.5L16 9"/>',
  portfolio:   '<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"/>',
  stress:      '<path d="M13 2L3 14h7l-1 8 10-12h-7z"/>',
  attribution: '<circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 010 20M12 12l7-7M12 12h10"/>',
  altdata:     '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>',
  models:      '<circle cx="12" cy="12" r="2"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/>',
  pipeline:    '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  logs:        '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
};

function homeIcon(key, cls) {
  return `<svg class="${cls || ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${HOME_ICONS[key] || ''}</svg>`;
}

/* Accent per tile. Grouped families rather than a rainbow: the data shelf runs
   teal, research runs indigo, edges emerald, risk warm, ops sky. */
const HOME_GROUPS = [
  { key: 'data',     tiles: ['inventory', 'download', 'quality'] },
  { key: 'research', tiles: ['research', 'insights', 'lab', 'report'] },
  { key: 'edge',     tiles: ['edges', 'trials', 'capacity', 'crossex'] },
  { key: 'risk',     tiles: ['fleet', 'portfolio', 'stress', 'attribution', 'altdata'] },
  { key: 'ops',      tiles: ['pipeline', 'models', 'logs'] },
];

const HOME_ACCENT = {
  inventory: '#2dd4bf', download: '#22d3ee', quality: '#5eead4',
  research: '#818cf8', insights: '#c084fc', lab: '#a78bfa', report: '#a5b4fc',
  edges: '#34d399', trials: '#4ade80', capacity: '#6ee7b7', crossex: '#10b981',
  fleet: '#fb923c', portfolio: '#fbbf24', stress: '#f87171',
  attribution: '#fb7185', altdata: '#fdba74',
  pipeline: '#38bdf8', models: '#7dd3fc', logs: '#94a3b8',
};

const homeState = { data: null, filter: 'all', timer: null, loading: false, error: null };

// ═════════════════════════════════════════════════════════════ FORMATTERS
/* Local escaper — app.js has its own `esc`, and two top-level consts of the
   same name in sibling classic scripts is a redeclaration error. */
const hEsc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const hNum = (v, d = 0) => (v == null || v !== v ? '—' :
  Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));

function hCompact(v) {
  if (v == null || v !== v) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'K';
  return String(Math.round(v * 100) / 100);
}

/* Sign goes outside the symbol: `-$14.3`, never `$-14.3`. */
const hUsd = v => (v == null || v !== v ? '—'
  : (v < 0 ? '-$' : '$') + hCompact(Math.abs(v)));
const hPct = (v, d = 1) => (v == null || v !== v ? '—' : Number(v).toFixed(d) + '%');
const hSign = (v, d = 1) => (v == null || v !== v ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(d));
const hTone = v => (v == null ? '' : v > 0 ? 'tone-pos' : v < 0 ? 'tone-neg' : 'tone-mute');

/* Relative age, rounded to the unit a human would say it in. */
function hAgo(hours) {
  if (hours == null || hours !== hours) return t('home_never');
  if (hours < 1 / 60) return t('home_just_now');
  if (hours < 1) return t('home_ago_min', { n: Math.max(1, Math.round(hours * 60)) });
  if (hours < 48) return t('home_ago_hour', { n: Math.round(hours) });
  return t('home_ago_day', { n: Math.round(hours / 24) });
}

/* Freshness → status dot. Thresholds are per-tile, in hours. */
function hFresh(hours, warnH, badH) {
  if (hours == null) return 'muted';
  if (hours > badH) return 'bad';
  if (hours > warnH) return 'warn';
  return 'ok';
}

// ═════════════════════════════════════════════════════════════ THE ONE CHART
/* A tile gets three numbers and exactly one chart, and that chart has to look
   right whether the row is 130px tall on a small laptop or 210px on a large
   one. All three variants below stretch: they own the leftover flex space
   instead of assuming a fixed height. */

/* Column strip — the default. Categories across, value above, label below. */
function svgCols(items, opts) {
  const o = Object.assign({ max: 4, fmt: hCompact, keyFmt: k => k, signed: false }, opts || {});
  const rows = (items || []).filter(r => r && r.v != null && r.v === r.v).slice(0, o.max);
  if (!rows.length) return `<div class="mcols"></div>`;
  const peak = Math.max(...rows.map(r => Math.abs(r.v))) || 1;
  return `<div class="mcols">${rows.map(r => {
    const h = Math.max(3, (Math.abs(r.v) / peak) * 100);
    const cls = o.signed ? (r.v >= 0 ? ' pos' : ' neg') : '';
    return `<div class="mcol" title="${hEsc(o.keyFmt(r.k))}: ${hEsc(String(o.fmt(r.v)))}">
      <span class="v">${hEsc(String(o.fmt(r.v)))}</span>
      <span class="t"><span class="bar${cls}" style="height:${h.toFixed(1)}%"></span></span>
      <span class="k">${hEsc(o.keyFmt(r.k))}</span>
    </div>`;
  }).join('')}</div>`;
}

/* Area sparkline with a hover readout, for the tiles whose story is a trend. */
function svgSpark(vals, opts) {
  const o = Object.assign({ unit: '', digits: 1 }, opts || {});
  const clean = (vals || []).filter(v => v != null && v === v);
  if (clean.length < 2) return `<div class="mcols"></div>`;
  const W = 100, H = 40;
  const lo = Math.min(...clean), hi = Math.max(...clean), span = hi - lo || 1;
  const x = i => (i / (clean.length - 1)) * W;
  const y = v => H - 3 - ((v - lo) / span) * (H - 9);
  const line = clean.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join('');
  const id = 'sp' + Math.random().toString(36).slice(2, 8);
  const last = clean[clean.length - 1];
  return `<div class="spark-wrap" data-vals="${clean.join(',')}" data-digits="${o.digits}"
      data-unit="${hEsc(o.unit)}" onmousemove="homeSparkMove(event,this)" onmouseleave="homeSparkOut(this)">
    <span class="spark-read">${last.toFixed(o.digits)}${hEsc(o.unit)}</span>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--acc)" stop-opacity=".34"/>
        <stop offset="100%" stop-color="var(--acc)" stop-opacity="0"/>
      </linearGradient></defs>
      <path d="${line}L${W},${H}L0,${H}Z" fill="url(#${id})"/>
      <path d="${line}" fill="none" stroke="var(--acc)" stroke-width="1.6"
            vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <circle class="sp-dot" cx="${x(clean.length - 1)}" cy="${y(last)}" r="2"
              fill="var(--acc)" vector-effect="non-scaling-stroke"/>
    </svg>
  </div>`;
}

function homeSparkMove(ev, el) {
  const vals = el.dataset.vals.split(',').map(Number);
  const r = el.getBoundingClientRect();
  // SVG user space is always left-to-right — CSS `direction` does not mirror it,
  // so the pointer maps straight onto the index in both FA and EN.
  const f = (ev.clientX - r.left) / r.width;
  const i = Math.min(vals.length - 1, Math.max(0, Math.round(f * (vals.length - 1))));
  el.querySelector('.spark-read').textContent =
    vals[i].toFixed(+el.dataset.digits) + el.dataset.unit;
  const dot = el.querySelector('.sp-dot');
  if (dot) dot.setAttribute('cx', (i / (vals.length - 1)) * 100);
}

function homeSparkOut(el) {
  const vals = el.dataset.vals.split(',').map(Number);
  el.querySelector('.spark-read').textContent =
    vals[vals.length - 1].toFixed(+el.dataset.digits) + el.dataset.unit;
  const dot = el.querySelector('.sp-dot');
  if (dot) dot.setAttribute('cx', 100);
}

/* A labelled ratio, for the tiles whose story is "x out of y". */
function meter(value, max, opts) {
  const o = Object.assign({ left: '', right: '', tone: 'var(--acc)' }, opts || {});
  const pct = max ? +Math.min(100, Math.max(0, (value / max) * 100)).toFixed(1) : 0;
  return `<div class="meter">
    <div class="meter-top"><span>${hEsc(o.left)}</span><span>${hEsc(o.right)}</span></div>
    <div class="meter-track">
      <div class="meter-fill" style="width:${pct}%;background:${o.tone}"></div>
    </div></div>`;
}

function kpis(items) {
  return `<div class="kpis${items.length === 2 ? ' c2' : ''}">${items.map(k => `
    <div class="kpi${k.hero ? ' hero' : ''}">
      <div class="l" title="${hEsc(k.l)}">${hEsc(k.l)}</div>
      <div class="v ${k.tone || ''}">${k.v}${k.u ? `<span class="u">${hEsc(k.u)}</span>` : ''}</div>
    </div>`).join('')}</div>`;
}

// ═════════════════════════════════════════════════════════════ TILE BODIES
/* Three numbers and one chart, every tile the same shape. Anything more stops
   being readable at the row height a nineteen-tile screenful allows — the rest
   of each section's data is one click away. Every renderer must survive an
   empty payload: on a fresh install none of the artifacts exist yet. */
const HOME_RENDER = {

  inventory(d) {
    return {
      flag: { dot: hFresh(d.newest_age_h, 12, 48) },
      body: kpis([
        { l: t('home_k_datasets'), v: hNum(d.n_datasets), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_size'), v: hNum(d.total_gb, 1), u: 'GB' },
      ]) + svgCols(d.by_timeframe, { max: 4, fmt: hCompact }),
    };
  },

  download(d) {
    return {
      flag: { dot: hFresh(d.newest_age_h, 12, 48) },
      body: kpis([
        { l: t('home_k_refreshed'), v: hNum(d.refreshed_24h), hero: true, tone: 'tone-acc' },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
        { l: t('home_k_week'), v: hCompact(d.refreshed_7d) },
      ]) + svgCols(d.by_exchange, { max: 4 }),
    };
  },

  quality(d) {
    const pct = d.scannable_pct;
    return {
      flag: { dot: pct == null ? 'muted' : pct >= 60 ? 'ok' : pct >= 40 ? 'warn' : 'bad' },
      body: kpis([
        { l: t('home_k_scannable'), v: hPct(pct, 0), hero: true, tone: 'tone-acc' },
        { l: t('home_k_median_bars'), v: hCompact(d.median_bars) },
        { l: t('home_k_stale3d'), v: hNum(d.stale_gt_3d), tone: d.stale_gt_3d > 0 ? 'tone-warn' : '' },
      ]) + svgCols(d.bars_hist, { max: 4 }),
    };
  },

  research(d) {
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_ready_ds'), v: hNum(d.n_datasets), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_runs'), v: hNum(d.n_runs) },
      ]) + svgCols(d.by_timeframe, { max: 4, fmt: hCompact }),
    };
  },

  insights(d) {
    const risk = d.event_risk;
    return {
      flag: { chip: t('home_chip_tool'),
              dot: risk == null ? '' : risk > 0.5 ? 'bad' : risk > 0.3 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_event_risk'), v: hNum(risk, 2), hero: true,
          tone: risk > 0.5 ? 'tone-neg' : risk > 0.3 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1) },
        { l: t('home_k_ls'), v: hNum(d.ls_ratio_btc, 2),
          tone: d.ls_ratio_btc > 1 ? 'tone-pos' : 'tone-neg' },
      ]) + svgCols(d.top_strategies, { max: 4, keyFmt: k => (STRATEGY_LABELS[k] || k) }),
    };
  },

  lab(d) {
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_strategies'), v: hNum(d.n_strategies), hero: true },
        { l: t('home_k_params'), v: hNum(d.n_params) },
        { l: t('home_k_ready_ds'), v: hCompact(d.n_datasets) },
      ]) + svgCols(d.by_timeframe, { max: 4, fmt: hCompact }),
    };
  },

  report(d) {
    const b = d.best || {};
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_best_sharpe'), v: hSign(b.oos_sharpe, 1), hero: true, tone: hTone(b.oos_sharpe) },
        { l: t('home_k_oos_ret'), v: b.oos_mean_return == null ? '—' : hPct(b.oos_mean_return * 100, 0),
          tone: hTone(b.oos_mean_return) },
        { l: t('home_k_ranked'), v: hNum(d.n_top) },
      ]) + svgSpark(d.sharpes, { digits: 1 }),
    };
  },

  edges(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72), chip: d.live_timeframe || '' },
      body: kpis([
        { l: t('home_k_deployable'), v: hNum(d.n_deployable), hero: true, tone: 'tone-acc' },
        { l: t('home_k_passed'), v: hCompact(d.n_passed) },
        { l: t('home_k_pbo'), v: hPct((d.median_pbo || 0) * 100, 0),
          tone: d.median_pbo > 0.5 ? 'tone-neg' : d.median_pbo > 0.35 ? 'tone-warn' : 'tone-pos' },
      ]) + svgCols(d.by_timeframe_robust, { max: 4 }),
    };
  },

  trials(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_unique'), v: hCompact(d.n_unique), hero: true },
        { l: t('home_k_pass_rate'), v: hPct(d.pass_rate, 1), tone: 'tone-acc' },
        { l: t('home_k_deflated'), v: hNum(d.n_deflated_pass),
          tone: d.n_deflated_pass ? 'tone-pos' : 'tone-warn' },
      ]) + svgCols(d.strategies, { max: 4, fmt: v => hPct(v, 0),
                                   keyFmt: k => (STRATEGY_LABELS[k] || k) }),
    };
  },

  capacity(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_median_cap'), v: hUsd(d.median_capacity), hero: true },
        { l: t('home_k_total_cap'), v: hUsd(d.total_capacity) },
        { l: t('home_k_books'), v: hNum(d.n_books) },
      ]) + svgCols((d.rows || []).map(r => ({ k: r.symbol, v: r.capacity })),
                   { max: 4, fmt: hUsd, keyFmt: k => String(k || '').replace(/USDT$/, '') }),
    };
  },

  crossex(d) {
    return {
      flag: { chip: 'α', dot: hFresh(d.carry_age_h, 8, 26) },
      body: kpis([
        { l: t('home_k_best_carry'), v: hPct(d.best_spread, 0), hero: true, tone: 'tone-acc' },
        { l: t('home_k_multivenue'), v: hNum(d.multi_venue_symbols) },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
      ]) + svgCols((d.carry || []).map(c => ({ k: c.base, v: c.spread })),
                   { max: 4, fmt: v => hPct(v, 0) }),
    };
  },

  fleet(d) {
    const levPct = d.max_gross_leverage ? (d.gross_leverage / d.max_gross_leverage) * 100 : 0;
    return {
      flag: { dot: d.n_alerts > 0 ? 'bad' : hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_equity'), v: hUsd(d.equity_usd), hero: true },
        { l: t('home_k_gross_lev'), v: hNum(d.gross_leverage, 2), u: '×',
          tone: levPct > 80 ? 'tone-neg' : levPct > 50 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_net_delta'), v: hSign(d.net_beta_delta_pct, 1), u: '%',
          tone: hTone(d.net_beta_delta_pct) },
      ]) + svgCols((d.bots || []).filter(b => b.trades_30d)
                     .map(b => ({ k: b.bot, v: b.net_30d })),
                   { max: 5, fmt: v => hUsd(v), signed: true }),
    };
  },

  portfolio(d) {
    return {
      flag: { dot: hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_book'), v: hUsd(d.gross_usd), hero: true },
        { l: t('home_k_hhi'), v: hNum(d.hhi, 2), tone: d.hhi > 0.3 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_assets_n'), v: hNum(d.n_assets) },
      ]) + svgCols((d.top || []).map(a => ({ k: a.base, v: a.pct })),
                   { max: 5, fmt: v => hPct(v, 0) }),
    };
  },

  stress(d) {
    const w = d.worst || {};
    return {
      flag: { dot: d.n_liquidations > 0 ? 'bad' : hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_worst_loss'), v: hUsd(w.loss), hero: true, tone: hTone(w.loss) },
        { l: t('home_k_of_equity'), v: hSign(w.loss_pct, 1), u: '%', tone: hTone(w.loss_pct) },
        { l: t('home_k_liquidations'), v: hNum(d.n_liquidations),
          tone: d.n_liquidations ? 'tone-neg' : 'tone-pos' },
      ]) + svgCols((d.rows || []).map(r => ({ k: r.key, v: Math.abs(r.loss || 0) })),
                   { max: 4, fmt: v => '-' + hUsd(v),
                     keyFmt: k => String(k || '').split('_')[0] }),
    };
  },

  attribution(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_net'), v: hUsd(d.net), hero: true, tone: hTone(d.net) },
        { l: t('home_k_intended'), v: hUsd(d.intended), tone: hTone(d.intended) },
        { l: t('home_k_mfe'), v: hPct((d.mfe_capture_avg || 0) * 100, 0),
          tone: hTone(d.mfe_capture_avg) },
      ]) + svgCols([
        { k: t('home_a_intended'), v: d.intended },
        { k: t('home_a_fees'), v: d.fees == null ? null : -Math.abs(d.fees) },
        { k: t('home_a_exit'), v: d.exit_slip },
        { k: t('home_a_funding'), v: d.funding },
      ], { fmt: v => hSign(v, 0), signed: true }),
    };
  },

  altdata(d) {
    return {
      flag: { dot: hFresh(d.age_h, 8, 24) },
      body: kpis([
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1), hero: true, tone: 'tone-acc' },
        { l: t('home_k_dvol_eth'), v: hNum(d.dvol_eth, 1) },
        { l: t('home_k_liq24'), v: hUsd(d.liquidations_24h_usd) },
      ]) + svgSpark(d.dvol_series, { digits: 1 }),
    };
  },

  pipeline(d) {
    const running = d.run_state === 'running';
    return {
      flag: {
        dot: running ? 'live' : d.healthy === false ? 'bad' : (d.late || d.missing) ? 'warn' : 'ok',
        chip: running ? t('home_running') : '',
      },
      body: kpis([
        { l: t('home_k_jobs_ok'), v: `${hNum(d.ok)}<span class="u">/${hNum(d.n_jobs)}</span>`,
          hero: true, tone: d.late || d.missing ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_late'), v: hNum(d.late), tone: d.late ? 'tone-warn' : '' },
        { l: t('home_k_missing'), v: hNum(d.missing), tone: d.missing ? 'tone-neg' : '' },
      ]) + meter(d.ok, d.n_jobs, {
        left: running ? t('home_pipe_running_short', {
                step: stageLabel(d.run_step) || (d.run_step || '') })
                      : t('home_pipe_fresh'),
        right: hAgo(d.age_h),
        tone: d.late || d.missing ? 'var(--yellow)' : 'var(--green)',
      }),
    };
  },

  models(d) {
    return {
      flag: { dot: hFresh(d.age_h, 26, 72) },
      body: kpis([
        { l: t('home_k_live_pairs'), v: hNum(d.n_pairs), hero: true },
        { l: t('home_k_bots'), v: hNum(d.n_bots) },
        { l: t('home_k_dropped'), v: hNum(d.n_dropped), tone: d.n_dropped ? 'tone-warn' : '' },
      ]) + svgCols((d.bots || []).map(b => ({ k: b.bot, v: b.net_30d })),
                   { max: 4, fmt: hUsd, signed: true }),
    };
  },

  logs(d) {
    const bad = d.n_errors > 0;
    return {
      flag: { dot: bad ? 'bad' : d.n_warnings > 0 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_errors'), v: hNum(d.n_errors), hero: true, tone: bad ? 'tone-neg' : 'tone-pos' },
        { l: t('home_k_warnings'), v: hNum(d.n_warnings), tone: d.n_warnings ? 'tone-warn' : '' },
        { l: t('home_k_lines'), v: hCompact(d.n_lines) },
      ]) + svgCols(d.levels, { max: 5 }),
    };
  },
};

// ═════════════════════════════════════════════════════════════ RENDER
function paintTile(host, key, data) {
  const r = (HOME_RENDER[key] || (() => ({ body: '', flag: {} })))(data || {});
  const flag = r.flag || {};
  host.innerHTML = `
    <div class="tile-head">
      <div class="tile-glyph">${homeIcon(key)}</div>
      <div class="tile-id">
        <div class="n" title="${hEsc(t('sub_' + key))}">${hEsc(t('nav_' + key))}</div>
      </div>
      <div class="tile-flag">
        ${flag.chip ? `<span class="tile-chip">${hEsc(flag.chip)}</span>` : ''}
        ${flag.dot ? `<span class="tile-status ${flag.dot === 'muted' ? '' : flag.dot}"></span>` : ''}
      </div>
    </div>
    ${r.body}`;
}

/* One grid sized to the viewport: fixed column and row counts with `1fr` rows,
   so all nineteen tiles land on a single laptop screen and each one gets an
   equal share of whatever height that screen has. */
function renderHome() {
  const wrap = document.getElementById('home-grid-host');
  if (!wrap) return;
  const d = homeState.data;
  const tiles = HOME_GROUPS.flatMap(g => g.tiles.map(k => ({ k, g: g.key })));

  wrap.innerHTML = tiles.map(({ k, g }) => `
    <article class="tile${d ? '' : ' skeleton'}"
      data-tile="${k}" data-group="${g}" style="--acc:${HOME_ACCENT[k]}"
      tabindex="0" role="button" aria-label="${hEsc(t('nav_' + k))}"
      onclick="showSection('${k}')"
      onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showSection('${k}')}">
      ${d ? '' : skeletonTile()}
    </article>`).join('');

  renderHomeFilter();
  applyHomeFilter();
  if (!d) return;
  wrap.querySelectorAll('.tile').forEach(el => {
    paintTile(el, el.dataset.tile, d.tiles[el.dataset.tile] || {});
  });
}

function skeletonTile() {
  return `<div class="tile-head">
      <div class="sk" style="width:26px;height:26px;border-radius:8px"></div>
      <div style="flex:1"><div class="sk" style="height:10px;width:56%"></div></div>
    </div>
    <div class="sk" style="height:26px;width:46%"></div>
    <div class="sk" style="flex:1;min-height:0"></div>`;
}

/* Group chips double as the legend for the accent colours. */
function renderHomeFilter() {
  const host = document.getElementById('home-filter');
  if (!host) return;
  const cur = homeState.filter || 'all';
  const total = HOME_GROUPS.reduce((n, g) => n + g.tiles.length, 0);
  host.innerHTML = `
    <button class="fchip ${cur === 'all' ? 'on' : ''}" onclick="homeFilter('all')">
      ${hEsc(t('home_all'))}<span class="n">${total}</span></button>
    ` + HOME_GROUPS.map(g => `
    <button class="fchip ${cur === g.key ? 'on' : ''}" onclick="homeFilter('${g.key}')"
      style="color:${cur === g.key ? HOME_ACCENT[g.tiles[0]] : ''}">
      <span class="swatch" style="background:${HOME_ACCENT[g.tiles[0]]}"></span>
      ${hEsc(t('home_g_' + g.key))}<span class="n">${g.tiles.length}</span></button>`).join('');
}

function homeFilter(group) {
  homeState.filter = group;
  renderHomeFilter();
  applyHomeFilter();
}

/* Filtering hides tiles outright, so the surviving ones grow to fill the grid. */
function applyHomeFilter() {
  const cur = homeState.filter || 'all';
  const grid = document.getElementById('home-grid-host');
  if (!grid) return;
  let shown = 0;
  grid.querySelectorAll('.tile').forEach(el => {
    const hide = cur !== 'all' && el.dataset.group !== cur;
    el.classList.toggle('hidden', hide);
    if (!hide) shown++;
  });
  // Re-shape the grid so a filtered view is not one thin row of stretched tiles.
  const cols = Math.min(5, Math.max(2, Math.ceil(Math.sqrt(shown * 1.6))));
  grid.style.gridTemplateColumns = cur === 'all' ? '' : `repeat(${cols},minmax(0,1fr))`;
  grid.style.gridTemplateRows = cur === 'all' ? '' : `repeat(${Math.ceil(shown / cols)},minmax(0,1fr))`;
}

// ═════════════════════════════════════════════════════════════ DATA
async function loadHome(force) {
  if (homeState.loading) return;
  homeState.loading = true;
  if (!homeState.data) renderHome();          // paint skeletons on first entry
  try {
    const r = await fetch('/api/home/summary' + (force ? '?refresh=1' : ''));
    homeState.data = await r.json();
    homeState.error = null;
  } catch (e) {
    homeState.error = String(e);
  } finally {
    homeState.loading = false;
  }
  renderHome();
  syncRailStats();
}

/* Poll only while the launcher is the visible section — the tiles are cheap but
   there is no reason to hit the API from behind another view. */
function homeAutoRefresh(on) {
  if (homeState.timer) { clearInterval(homeState.timer); homeState.timer = null; }
  if (on) homeState.timer = setInterval(() => loadHome(false), 60000);
}

// ═════════════════════════════════════════════════════════════ SIDEBAR
/* One number per row, so the menu itself carries state. Kept to the single
   figure each section is really judged on. */
function railStat(key, T) {
  const d = T[key] || {};
  switch (key) {
    case 'inventory': return hCompact(d.n_datasets);
    case 'download': return hCompact(d.refreshed_24h);
    case 'quality': return d.scannable_pct == null ? '' : Math.round(d.scannable_pct) + '%';
    case 'research': return d.n_runs ? hCompact(d.n_runs) : '';
    case 'report': return hSign((d.best || {}).oos_sharpe, 1);
    case 'insights': return hNum(d.event_risk, 2);
    case 'lab': return hNum(d.n_strategies);
    case 'edges': return hNum(d.n_deployable);
    case 'trials': return d.pass_rate == null ? '' : d.pass_rate + '%';
    case 'capacity': return hUsd(d.median_capacity);
    case 'crossex': return d.best_spread == null ? '' : Math.round(d.best_spread) + '%';
    case 'fleet': return hNum(d.gross_leverage, 2) + '×';
    case 'portfolio': return hUsd(d.gross_usd);
    case 'stress': return hUsd((d.worst || {}).loss);
    case 'attribution': return hUsd(d.net);
    case 'altdata': return hNum(d.dvol_btc, 1);
    case 'models': return hNum(d.n_pairs);
    case 'pipeline': return `${hNum(d.ok)}/${hNum(d.n_jobs)}`;
    case 'logs': return hNum(d.n_errors);
    default: return '';
  }
}

/* Which sections currently want attention — drives the red dot in the menu. */
function railAlerts(T) {
  return {
    fleet: (T.fleet || {}).n_alerts > 0,
    pipeline: (T.pipeline || {}).healthy === false || (T.pipeline || {}).missing > 0
              || (T.pipeline || {}).late > 0,
    logs: (T.logs || {}).n_errors > 0,
  };
}

function buildRail() {
  const host = document.getElementById('rail-scroll');
  if (!host) return;
  host.innerHTML = HOME_GROUPS.map(g => `
    <div class="rail-group">${hEsc(t('home_g_' + g.key))}</div>
    ` + g.tiles.map(k => `
      <div class="rail-item" data-section="${k}" style="--acc:${HOME_ACCENT[k]}"
        tabindex="0" role="button" aria-label="${hEsc(t('nav_' + k))}"
        onclick="showSection('${k}')"
        onkeydown="if(event.key==='Enter'){showSection('${k}')}">
        ${homeIcon(k)}<span class="lbl">${hEsc(t('nav_' + k))}</span>
        <span class="kpi-mini" data-stat="${k}"></span>
        <span class="tip">${hEsc(t('nav_' + k))}</span>
      </div>`).join('')).join('');

  // A language flip rebuilds the menu from scratch; re-mark whichever section
  // is on screen so the active row survives it.
  const open = (document.querySelector('.section.active') || {}).id;
  if (open) {
    const item = document.querySelector(`.rail-item[data-section="${open.replace('sec-', '')}"]`);
    if (item) item.classList.add('active');
  }
  syncRailStats();
}

function syncRailStats() {
  if (!homeState.data) return;
  const T = homeState.data.tiles;
  const alerts = railAlerts(T);
  document.querySelectorAll('.rail-item').forEach(item => {
    const key = item.dataset.section;
    const cell = item.querySelector('.kpi-mini');
    if (cell) cell.textContent = railStat(key, T);
    let dot = item.querySelector('.dot');
    if (alerts[key] && !dot) {
      dot = document.createElement('span');
      dot.className = 'dot';
      item.appendChild(dot);
    } else if (!alerts[key] && dot) {
      dot.remove();
    }
  });
}

function toggleRail(force) {
  const app = document.getElementById('app');
  const on = force != null ? force : !app.classList.contains('rail-collapsed');
  app.classList.toggle('rail-collapsed', on);
  try { localStorage.setItem('qr_rail_collapsed', on ? '1' : '0'); } catch (e) {}
}

function restoreRail() {
  let v = null;
  try { v = localStorage.getItem('qr_rail_collapsed'); } catch (e) {}
  if (v === '1') toggleRail(true);
}

// ═════════════════════════════════════════════════════════════ COMMAND PALETTE
const cmdk = { open: false, sel: 0, list: [] };

function cmdkAll() {
  const out = [];
  HOME_GROUPS.forEach(g => g.tiles.forEach(k => out.push({
    key: k, name: t('nav_' + k), sub: t('sub_' + k), group: t('home_g_' + g.key),
  })));
  return out;
}

function toggleCmdk(force) {
  cmdk.open = force != null ? force : !cmdk.open;
  const el = document.getElementById('cmdk');
  el.classList.toggle('open', cmdk.open);
  if (cmdk.open) {
    const input = document.getElementById('cmdk-input');
    input.value = '';
    cmdk.sel = 0;
    cmdkFilter('');
    setTimeout(() => input.focus(), 20);
  }
}

/* Substring match over the FA name, the EN name and the section key, so either
   language (or the URL-ish key) finds the same section. */
function cmdkFilter(q) {
  const needle = (q || '').trim().toLowerCase();
  const all = cmdkAll();
  cmdk.list = !needle ? all : all.filter(it => {
    const hay = [it.name, it.sub, it.key,
      (I18N.fa[`nav_${it.key}`] || ''), (I18N.en[`nav_${it.key}`] || '')].join(' ').toLowerCase();
    return hay.includes(needle);
  });
  if (cmdk.sel >= cmdk.list.length) cmdk.sel = 0;
  const host = document.getElementById('cmdk-results');
  host.innerHTML = cmdk.list.length ? cmdk.list.map((it, i) => `
    <div class="res ${i === cmdk.sel ? 'sel' : ''}" data-i="${i}"
      onmouseenter="cmdk.sel=${i};cmdkPaintSel()" onclick="cmdkGo(${i})">
      ${homeIcon(it.key)}<span class="n">${hEsc(it.name)}</span>
      <span class="g">${hEsc(it.group)}</span>
    </div>`).join('') : `<div class="none">${t('home_cmdk_none')}</div>`;
}

function cmdkPaintSel() {
  document.querySelectorAll('#cmdk-results .res').forEach(el =>
    el.classList.toggle('sel', +el.dataset.i === cmdk.sel));
}

function cmdkGo(i) {
  const it = cmdk.list[i];
  if (!it) return;
  toggleCmdk(false);
  showSection(it.key);
}

function cmdkKey(ev) {
  if (!cmdk.open) return;
  if (ev.key === 'Escape') { toggleCmdk(false); return; }
  if (ev.key === 'ArrowDown') {
    cmdk.sel = Math.min(cmdk.list.length - 1, cmdk.sel + 1); cmdkPaintSel();
    document.querySelector('#cmdk-results .res.sel')?.scrollIntoView({ block: 'nearest' });
    ev.preventDefault();
  } else if (ev.key === 'ArrowUp') {
    cmdk.sel = Math.max(0, cmdk.sel - 1); cmdkPaintSel();
    document.querySelector('#cmdk-results .res.sel')?.scrollIntoView({ block: 'nearest' });
    ev.preventDefault();
  } else if (ev.key === 'Enter') {
    cmdkGo(cmdk.sel); ev.preventDefault();
  }
}

document.addEventListener('keydown', ev => {
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
    ev.preventDefault(); toggleCmdk();
  } else if (cmdk.open) {
    cmdkKey(ev);
  }
});
