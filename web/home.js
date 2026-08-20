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

/* Tiles rendered at double width — the ones whose chart needs the room. */
const HOME_WIDE = new Set(['edges', 'fleet', 'attribution']);

const homeState = { data: null, seg: {}, filter: 'all', timer: null, loading: false, error: null };

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

/* Freshness → status dot. `warn`/`bad` thresholds are per-tile in hours. */
function hFresh(hours, warnH, badH) {
  if (hours == null) return 'muted';
  if (hours > badH) return 'bad';
  if (hours > warnH) return 'warn';
  return 'ok';
}

// ═════════════════════════════════════════════════════════════ MICRO CHARTS
/* Area sparkline with a hover readout. Values are carried on the element so the
   pointer handler can resolve an index without re-rendering anything. */
function svgSpark(vals, opts) {
  const o = Object.assign({ h: 46, unit: '', digits: 1 }, opts || {});
  const clean = (vals || []).filter(v => v != null && v === v);
  if (clean.length < 2) return `<div class="tile-note">${t('no_data')}</div>`;
  const W = 100, H = o.h;
  const lo = Math.min(...clean), hi = Math.max(...clean), span = hi - lo || 1;
  const x = i => (i / (clean.length - 1)) * W;
  const y = v => H - 4 - ((v - lo) / span) * (H - 10);
  const line = clean.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join('');
  const id = 'sp' + Math.random().toString(36).slice(2, 8);
  const last = clean[clean.length - 1];
  return `<div class="spark-wrap" data-vals="${clean.join(',')}" data-digits="${o.digits}"
      data-unit="${hEsc(o.unit)}" onmousemove="homeSparkMove(event,this)" onmouseleave="homeSparkOut(this)">
    <span class="spark-read">${last.toFixed(o.digits)}${hEsc(o.unit)}</span>
    <svg class="mchart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" height="${H}">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--acc)" stop-opacity=".34"/>
        <stop offset="100%" stop-color="var(--acc)" stop-opacity="0"/>
      </linearGradient></defs>
      <path d="${line}L${W},${H}L0,${H}Z" fill="url(#${id})"/>
      <path d="${line}" fill="none" stroke="var(--acc)" stroke-width="1.6"
            vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <circle class="sp-dot" cx="${x(clean.length - 1)}" cy="${y(last)}" r="2.4"
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
  const read = el.querySelector('.spark-read');
  read.textContent = vals[i].toFixed(+el.dataset.digits) + el.dataset.unit;
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

/* Horizontal bars — the workhorse for every "count by category" widget. */
function svgBars(items, opts) {
  const o = Object.assign({ max: 4, fmt: hNum, keyFmt: k => k }, opts || {});
  const rows = (items || []).filter(r => r && r.v != null).slice(0, o.max);
  if (!rows.length) return `<div class="tile-note">${t('no_data')}</div>`;
  const peak = Math.max(...rows.map(r => Math.abs(r.v))) || 1;
  return `<div class="mbars">${rows.map(r => `
    <div class="mbar" title="${hEsc(o.keyFmt(r.k))}: ${hEsc(String(o.fmt(r.v)))}">
      <span class="k">${hEsc(o.keyFmt(r.k))}</span>
      <span class="track"><span class="fill" style="width:${((Math.abs(r.v) / peak) * 100).toFixed(1)}%"></span></span>
      <span class="v">${hEsc(String(o.fmt(r.v)))}</span>
    </div>`).join('')}</div>`;
}

/* Diverging bars around a zero axis — used for PnL attribution components. */
function svgDiverging(items, opts) {
  const o = Object.assign({ fmt: hNum }, opts || {});
  const rows = (items || []).filter(r => r && r.v != null && r.v === r.v);
  if (!rows.length) return `<div class="tile-note">${t('no_data')}</div>`;
  const peak = Math.max(...rows.map(r => Math.abs(r.v))) || 1;
  return `<div class="mbars">${rows.map(r => {
    const w = +((Math.abs(r.v) / peak) * 50).toFixed(1);
    const pos = r.v >= 0;
    const col = pos ? 'var(--green)' : 'var(--red)';
    return `<div class="mbar" title="${hEsc(r.k)}: ${hEsc(String(o.fmt(r.v)))}">
      <span class="k">${hEsc(r.k)}</span>
      <span class="track" style="position:relative">
        <span class="fill" style="position:absolute;top:0;bottom:0;background:${col};
          ${pos ? 'inset-inline-start:50%' : 'inset-inline-end:50%'};width:${w}%"></span>
        <span style="position:absolute;inset-inline-start:50%;top:-1px;bottom:-1px;width:1px;background:var(--border2)"></span>
      </span>
      <span class="v">${hEsc(String(o.fmt(r.v)))}</span>
    </div>`;
  }).join('')}</div>`;
}

/* Concentration ring. Segments are drawn as dash-offset arcs on one circle so
   there is no path math to get wrong at odd percentages. */
function svgDonut(segs, opts) {
  const o = Object.assign({ size: 88, label: '', sub: '' }, opts || {});
  const rows = (segs || []).filter(s => s && s.pct > 0);
  if (!rows.length) return `<div class="tile-note">${t('no_data')}</div>`;
  const R = 15.915494, C = 2 * Math.PI * R;  // circumference == 100 → pct maps 1:1
  let off = 25;                              // start at 12 o'clock
  const shades = ['1', '.78', '.58', '.42', '.3', '.2'];
  const arcs = rows.map((s, i) => {
    const dash = `${(s.pct / 100) * C} ${C - (s.pct / 100) * C}`;
    const arc = `<circle cx="21" cy="21" r="${R}" fill="none" stroke="var(--acc)"
      stroke-opacity="${shades[i] || '.15'}" stroke-width="4.4"
      stroke-dasharray="${dash}" stroke-dashoffset="${off}"><title>${hEsc(s.k)} — ${s.pct}%</title></circle>`;
    off -= (s.pct / 100) * C;
    return arc;
  }).join('');
  return `<div style="display:flex;align-items:center;gap:13px">
    <svg viewBox="0 0 42 42" width="${o.size}" height="${o.size}" style="flex:none">
      <circle cx="21" cy="21" r="${R}" fill="none" stroke="rgba(255,255,255,.06)" stroke-width="4.4"/>
      ${arcs}
      <text x="21" y="21.6" text-anchor="middle" dominant-baseline="middle"
        fill="var(--text)" font-size="7.4" font-weight="700">${hEsc(o.label)}</text>
      <text x="21" y="26.4" text-anchor="middle" dominant-baseline="middle"
        fill="var(--text3)" font-size="3.4">${hEsc(o.sub)}</text>
    </svg>
    <div class="trows" style="flex:1;min-width:0">${rows.slice(0, 4).map((s, i) => `
      <div class="trow"><span style="width:7px;height:7px;border-radius:2px;background:var(--acc);
        opacity:${shades[i] || '.15'};flex:none"></span>
        <span class="a">${hEsc(s.k)}</span><span class="c">${s.pct}%</span></div>`).join('')}
    </div></div>`;
}

/* Single-track meter — a value read against its own ceiling. */
function meter(value, max, opts) {
  const o = Object.assign({ left: '', right: '', tone: 'var(--acc)' }, opts || {});
  const pct = max ? +Math.min(100, Math.max(0, (value / max) * 100)).toFixed(1) : 0;
  return `<div class="meter">
    <div class="meter-top"><span>${hEsc(o.left)}</span><span>${hEsc(o.right)}</span></div>
    <div class="meter-track">
      <div class="meter-fill" style="width:${pct}%;background:${o.tone}"></div>
    </div></div>`;
}

/* Funnel: each stage as a share of the widest one (scan → pass → deploy). */
function funnel(stages) {
  const rows = (stages || []).filter(s => s.v != null);
  if (!rows.length) return `<div class="tile-note">${t('no_data')}</div>`;
  const peak = Math.max(...rows.map(r => r.v)) || 1;
  return `<div class="mbars">${rows.map((r, i) => `
    <div class="mbar" title="${hEsc(r.k)}: ${hNum(r.v)}">
      <span class="k">${hEsc(r.k)}</span>
      <span class="track"><span class="fill"
        style="width:${Math.max(1.5, (r.v / peak) * 100).toFixed(1)}%;opacity:${(1 - i * 0.19).toFixed(2)}"></span></span>
      <span class="v">${hCompact(r.v)}</span>
    </div>`).join('')}</div>`;
}

function kpis(items, cols) {
  return `<div class="kpis c${cols || items.length}">${items.map(k => `
    <div class="kpi${k.hero ? ' hero' : ''}">
      <div class="l">${hEsc(k.l)}</div>
      <div class="v ${k.tone || ''}${k.sm ? ' sm' : ''}" style="unicode-bidi:isolate">${k.v}${
        k.u ? `<span class="u">${hEsc(k.u)}</span>` : ''}</div>
      ${k.d ? `<div class="d">${k.d}</div>` : ''}
    </div>`).join('')}</div>`;
}

function trows(rows) {
  if (!rows || !rows.length) return `<div class="tile-note">${t('no_data')}</div>`;
  return `<div class="trows">${rows.map((r, i) => `
    <div class="trow">
      ${r.rank !== false ? `<span class="rank">${i + 1}</span>` : ''}
      <span class="a">${r.a}</span>
      ${r.b ? `<span class="b">${r.b}</span>` : ''}
      ${r.c != null ? `<span class="c ${r.tone || ''}" style="unicode-bidi:isolate">${r.c}</span>` : ''}
    </div>`).join('')}</div>`;
}

/* In-tile segmented control. Clicks must not bubble to the card's navigation. */
function seg(tileKey, options, current) {
  return `<div class="tseg" onclick="event.stopPropagation()">${options.map(o => `
    <button class="${o.k === current ? 'on' : ''}"
      onclick="homeSetSeg('${tileKey}','${o.k}')">${hEsc(o.label)}</button>`).join('')}</div>`;
}

function homeSetSeg(tileKey, value) {
  homeState.seg[tileKey] = value;
  const host = document.querySelector(`.tile[data-tile="${tileKey}"]`);
  if (host && homeState.data) paintTile(host, tileKey, homeState.data.tiles[tileKey] || {});
}

const segOf = (key, dflt) => homeState.seg[key] || dflt;

// ═════════════════════════════════════════════════════════════ TILE BODIES
/* Each renderer returns { body, flag } — `flag` is the header status dot/chip.
   The shape is deliberately uniform so the wall reads evenly: a KPI strip, one
   micro-chart, then the rows the numbers came from. They must all survive an
   empty payload: the artifact behind a tile may not exist yet on a fresh
   install, and every tool tile has to work before anything has been run. */

/* A hairline caption above an in-tile table. */
const tsub = label => `<div class="tsub">${hEsc(label)}</div>`;

const HOME_RENDER = {

  inventory(d) {
    const mode = segOf('inventory', 'tf');
    const items = mode === 'tf' ? d.by_timeframe : d.by_exchange;
    return {
      flag: { dot: hFresh(d.newest_age_h, 12, 48) },
      body: kpis([
        { l: t('home_k_datasets'), v: hNum(d.n_datasets), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_size'), v: hNum(d.total_gb, 2), u: 'GB' },
        { l: t('home_k_fresh24'), v: hNum(d.fresh_24h), tone: 'tone-pos' },
      ], 2)
        + `<div class="tile-tools">
            ${seg('inventory', [{ k: 'tf', label: t('home_seg_tf') }, { k: 'ex', label: t('home_seg_venue') }], mode)}
            <span class="tile-note">${t('home_inv_stale', { n: hNum(d.stale_30d) })}</span>
          </div>`
        + svgBars(items, { max: 5 })
        + tsub(t('home_hdr_biggest'))
        + trows([{ a: `<b>${hEsc((d.biggest || {}).name || '—')}</b>`,
                   c: hNum((d.biggest || {}).mb, 1) + ' MB', rank: false }]),
    };
  },

  download(d) {
    return {
      flag: { dot: hFresh(d.newest_age_h, 12, 48) },
      body: kpis([
        { l: t('home_k_refreshed'), v: hNum(d.refreshed_24h), hero: true, tone: 'tone-acc' },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
        { l: t('home_k_week'), v: hNum(d.refreshed_7d) },
      ], 3)
        + svgBars(d.by_exchange, { max: 4 })
        + tsub(t('home_hdr_newest'))
        + trows((d.newest || []).slice(0, 3).map(x => ({
            a: `<b>${hEsc(x.name)}</b>`, c: hAgo(x.age_h), rank: false }))),
    };
  },

  quality(d) {
    const pct = d.scannable_pct;
    return {
      flag: { dot: pct == null ? 'muted' : pct >= 60 ? 'ok' : pct >= 40 ? 'warn' : 'bad' },
      body: kpis([
        { l: t('home_k_scannable'), v: hPct(pct), hero: true, tone: 'tone-acc' },
        { l: t('home_k_median_bars'), v: hCompact(d.median_bars) },
        { l: t('home_k_stale3d'), v: hNum(d.stale_gt_3d), tone: d.stale_gt_3d > 0 ? 'tone-warn' : '' },
      ], 3)
        + meter(d.n_scannable, d.n_datasets, {
            left: t('home_q_meter', { a: hNum(d.n_scannable), b: hNum(d.n_datasets) }),
            right: t('home_q_minbars', { n: hNum(d.min_scan_bars) }), tone: 'var(--acc)',
          })
        + tsub(t('home_hdr_bars'))
        + svgBars(d.bars_hist, { max: 4 })
        + tsub(t('home_hdr_stale'))
        + trows((d.stale_rows || []).slice(0, 2).map(r => ({
            a: `<b>${hEsc(shortDs(r.dataset))}</b>`, b: r.last,
            c: t('home_days', { n: hNum(r.days) }), tone: 'tone-warn', rank: false,
          }))),
    };
  },

  research(d) {
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_ready_ds'), v: hNum(d.n_datasets), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_runs'), v: hNum(d.n_runs) },
      ], 3)
        + tsub(t('home_hdr_recent'))
        + trows((d.recent || []).slice(0, 3).map(r => ({
            a: `<b>${hEsc(r.name || '')}</b> <span class="b">${hEsc(shortDs(r.target))}</span>`,
            b: hAgo(r.age_h),
            c: r.value == null ? '' : hNum(r.value, 2),
          })))
        + (!(d.recent || []).length ? `<div class="tile-note">${t('home_no_runs')}</div>` : '')
        + tsub(t('home_hdr_run_kinds'))
        + svgBars(d.by_name, { max: 3 })
        + `<div class="tile-note">${t('home_research_note')}</div>`,
    };
  },

  insights(d) {
    const risk = d.event_risk;
    return {
      flag: { chip: t('home_chip_tool'),
              dot: risk == null ? '' : risk > 0.5 ? 'bad' : risk > 0.3 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_symbols'), v: hNum(d.n_symbols), hero: true },
        { l: t('home_k_event_risk'), v: hNum(risk, 2),
          tone: risk > 0.5 ? 'tone-neg' : risk > 0.3 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1) },
        { l: t('home_k_ls'), v: hNum(d.ls_ratio_btc, 2),
          tone: d.ls_ratio_btc > 1 ? 'tone-pos' : 'tone-neg' },
      ], 2)
        + tsub(t('home_ins_top'))
        + svgBars(d.top_strategies, { max: 3, keyFmt: k => (STRATEGY_LABELS[k] || k) })
        + tsub(t('home_hdr_edge_tf'))
        + svgBars(d.top_timeframes, { max: 3 }),
    };
  },

  lab(d) {
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_strategies'), v: hNum(d.n_strategies), hero: true },
        { l: t('home_k_params'), v: hNum(d.n_params) },
        { l: t('home_k_ready_ds'), v: hCompact(d.n_datasets) },
      ], 3)
        + tsub(t('home_hdr_strategies'))
        + `<div style="display:flex;flex-wrap:wrap;gap:3px">${(d.strategies || []).slice(0, 7)
            .map(k => `<span class="tile-chip">${hEsc(STRATEGY_LABELS[k] || k)}</span>`).join('')}
           </div>`
        + tsub(t('home_hdr_by_tf'))
        + svgBars(d.by_timeframe, { max: 3 })
        + `<div class="tile-note">${t('home_lab_note')}</div>`,
    };
  },

  report(d) {
    const b = d.best || {};
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_best_sharpe'), v: hSign(b.oos_sharpe, 1), hero: true, tone: hTone(b.oos_sharpe) },
        { l: t('home_k_oos_ret'), v: b.oos_mean_return == null ? '—' : hPct(b.oos_mean_return * 100),
          tone: hTone(b.oos_mean_return) },
        { l: t('home_k_ranked'), v: hNum(d.n_top) },
      ], 3)
        + svgSpark(d.sharpes, { h: 44, digits: 1 })
        + tsub(t('home_hdr_leaderboard'))
        + trows((d.rows || []).slice(0, 4).map(r => ({
            a: `<b>${hEsc(r.symbol || '')}</b> <span class="b">${hEsc(STRATEGY_LABELS[r.strategy] || r.strategy || '')}</span>`,
            b: r.timeframe, c: hSign(r.sharpe, 1), tone: 'tone-pos',
          }))),
    };
  },

  edges(d) {
    const mode = segOf('edges', 'passed');
    const bars = mode === 'passed' ? d.by_timeframe : d.by_timeframe_robust;
    return {
      flag: { dot: hFresh(d.age_h, 30, 72), chip: d.live_timeframe || '' },
      body: kpis([
        { l: t('home_k_scanned'), v: hCompact(d.n_scanned), hero: true },
        { l: t('home_k_passed'), v: hCompact(d.n_passed) },
        { l: t('home_k_deployable'), v: hNum(d.n_deployable), tone: 'tone-acc' },
        { l: t('home_k_pbo'), v: hPct((d.median_pbo || 0) * 100, 0),
          tone: d.median_pbo > 0.5 ? 'tone-neg' : d.median_pbo > 0.35 ? 'tone-warn' : 'tone-pos' },
      ], 4)
        + `<div class="tile-tools">
            ${seg('edges', [{ k: 'passed', label: t('home_seg_passed') }, { k: 'robust', label: t('home_seg_robust') }], mode)}
            <span class="tile-note">${t('home_edges_reach', {
              n: hNum(d.n_symbols), a: hNum(d.n_alerts) })}</span>
          </div>`
        + `<div class="grid-2" style="gap:12px;grid-template-columns:1fr 1fr">
            <div>${tsub(t('home_hdr_by_tf'))}${svgBars(bars, { max: 4 })}
                 ${tsub(t('home_hdr_trend'))}${svgSpark(d.trend_passed, { h: 38, digits: 0 })}</div>
            <div>${tsub(t('home_hdr_top_edges'))}${trows((d.top || []).slice(0, 5).map(e => ({
              a: `<b>${hEsc(e.symbol || '')}</b> <span class="b">${hEsc(STRATEGY_LABELS[e.strategy] || e.strategy || '')}</span>`,
              b: e.timeframe, c: hSign(e.oos_sharpe, 1), tone: 'tone-pos',
            })))}</div>
          </div>`,
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
      ], 3)
        + funnel([
            { k: t('home_f_tested'), v: d.n_unique },
            { k: t('home_f_ever'), v: d.n_ever_passed },
            { k: t('home_f_deflated'), v: d.n_deflated_pass },
          ])
        + tsub(t('home_hdr_pass_by_strategy'))
        + svgBars(d.strategies, { max: 4, fmt: v => hPct(v, 1),
                                  keyFmt: k => (STRATEGY_LABELS[k] || k) })
        + `<div class="tile-note">${t('home_trials_runs', { n: hCompact(d.n_runs_total) })}</div>`,
    };
  },

  capacity(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_median_cap'), v: hUsd(d.median_capacity), hero: true },
        { l: t('home_k_total_cap'), v: hUsd(d.total_capacity) },
        { l: t('home_k_books'), v: hNum(d.n_books) },
      ], 3)
        + tsub(t('home_hdr_tightest'))
        + trows((d.rows || []).slice(0, 3).map(r => ({
            a: `<b>${hEsc(r.symbol || '')}</b> <span class="b">${hEsc(r.venue || '')}</span>`,
            b: hNum(r.edge_bps, 0) + ' bps', c: hUsd(r.capacity),
            tone: r.capacity < 25000 ? 'tone-warn' : '',
          })))
        + tsub(t('home_hdr_impact_k'))
        + svgBars(d.venues, { max: 4, fmt: v => (v == null ? '—' : v.toFixed(3)) }),
    };
  },

  crossex(d) {
    return {
      flag: { chip: 'α', dot: hFresh(d.carry_age_h, 8, 26) },
      body: kpis([
        { l: t('home_k_best_carry'), v: hPct(d.best_spread, 1), hero: true, tone: 'tone-acc' },
        { l: t('home_k_multivenue'), v: hNum(d.multi_venue_symbols) },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
      ], 3)
        + tsub(t('home_hdr_carry'))
        + trows((d.carry || []).slice(0, 4).map(c => ({
            a: `<b>${hEsc(c.base || '')}</b> <span class="b">${hEsc(c.short || '')}→${hEsc(c.long || '')}</span>`,
            c: hPct(c.spread, 1), tone: 'tone-pos',
          })))
        + tsub(t('home_hdr_venues'))
        + svgBars(d.by_exchange, { max: 3 }),
    };
  },

  fleet(d) {
    const mode = segOf('fleet', 'lev');
    const bars = (d.bots || []).map(b => ({
      k: b.bot, v: mode === 'lev' ? b.gross_leverage : mode === 'open' ? b.n_open : b.net_30d,
    }));
    const levPct = d.max_gross_leverage ? (d.gross_leverage / d.max_gross_leverage) * 100 : 0;
    return {
      flag: { dot: d.n_alerts > 0 ? 'bad' : hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_equity'), v: hUsd(d.equity_usd), hero: true },
        { l: t('home_k_gross_lev'), v: hNum(d.gross_leverage, 2), u: '×',
          tone: levPct > 80 ? 'tone-neg' : levPct > 50 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_net_delta'), v: hSign(d.net_beta_delta_pct, 1), u: '%', tone: hTone(d.net_beta_delta_pct) },
        { l: t('home_k_corr'), v: hNum(d.avg_pairwise_corr, 2),
          tone: d.avg_pairwise_corr > 0.6 ? 'tone-warn' : '' },
      ], 4)
        + meter(d.gross_leverage, d.max_gross_leverage, {
            left: t('home_fleet_lev_cap', { n: hNum(d.max_gross_leverage, 1) }),
            right: t('home_fleet_pos', { n: hNum(d.n_positions), b: hNum(d.n_bots) }),
            tone: levPct > 80 ? 'var(--red)' : 'var(--acc)',
          })
        + `<div class="tile-tools">${seg('fleet', [
            { k: 'lev', label: t('home_seg_lev') },
            { k: 'open', label: t('home_seg_open') },
            { k: 'pnl', label: t('home_seg_net30') }], mode)}
           <span class="tile-note">${d.n_alerts > 0
             ? t('home_fleet_alerts', { n: hNum(d.n_alerts) })
             : t('home_fleet_ok_stale', { n: hNum(d.n_stale_prices) })}</span></div>`
        + `<div class="grid-2" style="gap:12px;grid-template-columns:1fr 1fr">
            <div>${tsub(t('home_hdr_by_bot'))}${mode === 'pnl'
              ? svgDiverging(bars.slice(0, 6), { fmt: v => hSign(v, 0) })
              : svgBars(bars, { max: 6, fmt: v => (mode === 'lev' ? hNum(v, 2) + '×' : hNum(v)) })}</div>
            <div>${tsub(t('home_hdr_bots_30d'))}${trows((d.bots || [])
              .filter(b => b.trades_30d).slice(0, 5).map(b => ({
                a: `<b>${hEsc(b.bot || '')}</b> <span class="b">${hNum(b.trades_30d)} ${t('home_k_trades')}</span>`,
                b: 'PF ' + hNum(b.pf_30d, 2),
                c: hUsd(b.net_30d), tone: hTone(b.net_30d), rank: false,
              })))}</div>
          </div>`,
    };
  },

  portfolio(d) {
    return {
      flag: { dot: hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_book'), v: hUsd(d.gross_usd), hero: true },
        { l: t('home_k_hhi'), v: hNum(d.hhi, 3), tone: d.hhi > 0.3 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_assets_n'), v: hNum(d.n_assets) },
      ], 3)
        + svgDonut((d.top || []).map(a => ({ k: a.base, pct: a.pct })), {
            label: hPct((d.top || [])[0] ? d.top[0].pct : null, 0), sub: t('home_k_top1'),
          })
        + tsub(t('home_hdr_weights'))
        + trows((d.top || []).slice(0, 3).map(a => ({
            a: `<b>${hEsc(a.base || '')}</b>`,
            b: t('home_n_bots', { n: hNum(a.n_bots) }),
            c: hUsd(a.gross),
          }))),
    };
  },

  stress(d) {
    const w = d.worst || {};
    const label = LANG === 'fa' ? w.label_fa : w.label_en;
    return {
      flag: { dot: d.n_liquidations > 0 ? 'bad' : hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_worst_loss'), v: hUsd(w.loss), hero: true, tone: hTone(w.loss) },
        { l: t('home_k_of_equity'), v: hSign(w.loss_pct, 2), u: '%', tone: hTone(w.loss_pct) },
        { l: t('home_k_liquidations'), v: hNum(d.n_liquidations),
          tone: d.n_liquidations ? 'tone-neg' : 'tone-pos' },
      ], 3)
        + tsub(t('home_hdr_loss_spread'))
        + svgBars((d.rows || []).map(r => ({ k: r.key, v: Math.abs(r.loss || 0) })),
                  { max: 3, fmt: v => '-' + hUsd(v) })
        + tsub(t('home_hdr_scenarios', { n: hNum(d.n_scenarios) }))
        + trows((d.rows || []).slice(0, 3).map(r => ({
            a: `<b>${hEsc((LANG === 'fa' ? r.label_fa : r.label_en) || r.key || '')}</b>`,
            c: hUsd(r.loss), tone: hTone(r.loss), rank: false,
          }))),
    };
  },

  attribution(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_net'), v: hUsd(d.net), hero: true, tone: hTone(d.net) },
        { l: t('home_k_intended'), v: hUsd(d.intended), tone: hTone(d.intended) },
        { l: t('home_k_fees'), v: hUsd(-Math.abs(d.fees || 0)), tone: 'tone-neg' },
        { l: t('home_k_mfe'), v: hPct((d.mfe_capture_avg || 0) * 100, 0),
          tone: hTone(d.mfe_capture_avg) },
      ], 4)
        + `<div class="grid-2" style="gap:10px;grid-template-columns:1fr 1fr">
            <div>${tsub(t('home_hdr_components'))}${svgDiverging([
              { k: t('home_a_intended'), v: d.intended },
              { k: t('home_a_fees'), v: d.fees == null ? null : -Math.abs(d.fees) },
              { k: t('home_a_exit'), v: d.exit_slip },
              { k: t('home_a_funding'), v: d.funding },
              { k: t('home_a_entry'), v: d.entry_slip },
            ], { fmt: v => hSign(v, 0) })}</div>
            <div>${tsub(t('home_hdr_drag_by_bot'))}${trows((d.rows || []).slice(0, 5).map(r => ({
              a: `<b>${hEsc(r.bot || '')}</b>`, b: hNum(r.n_trades),
              c: hUsd(r.drag), tone: 'tone-neg', rank: false,
            })))}</div>
          </div>`
        + `<div class="tile-note">${t('home_attr_window', { d: hNum(d.window_days) })}</div>`,
    };
  },

  altdata(d) {
    return {
      flag: { dot: hFresh(d.age_h, 8, 24) },
      body: kpis([
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1), hero: true, tone: 'tone-acc' },
        { l: t('home_k_dvol_eth'), v: hNum(d.dvol_eth, 1) },
        { l: t('home_k_liq24'), v: hUsd(d.liquidations_24h_usd) },
        { l: t('home_k_ls'), v: hNum(d.ls_ratio_btc, 2),
          tone: d.ls_ratio_btc > 1 ? 'tone-pos' : 'tone-neg' },
      ], 2)
        + svgSpark(d.dvol_series, { h: 34, digits: 1 })
        + tsub(t('home_hdr_funding_extremes'))
        + trows((d.funding_rows || []).slice(0, 3).map(f => ({
            a: `<b>${hEsc(f.symbol || '')}</b>`,
            b: hNum(f.premium_bps, 0) + ' bps',
            c: hSign(f.ann, 0) + '%', tone: hTone(f.ann), rank: false,
          }))),
    };
  },

  pipeline(d) {
    const running = d.run_state === 'running';
    const scanPct = d.scan_total ? Math.round((d.scan_done / d.scan_total) * 100) : null;
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
      ], 3)
        + meter(d.ok, d.n_jobs, {
            left: t('home_pipe_fresh'), right: hAgo(d.age_h),
            tone: d.late || d.missing ? 'var(--yellow)' : 'var(--green)',
          })
        + (running
            ? `<div class="tile-note">${t('home_pipe_running', {
                step: stageLabel(d.run_step) || (d.run_step || ''),
                for: hAgo(d.run_started_age_h) })}${scanPct != null ? ` · ${scanPct}%` : ''}</div>`
            : '')
        + tsub(t('home_hdr_jobs'))
        + trows((d.jobs || []).slice(0, 4).map(j => ({
            a: `<b>${hEsc(j.name || '')}</b>`,
            b: t('pipe_s_' + (j.status || 'ok')),
            c: hAgo(j.age_h),
            tone: j.status === 'missing' ? 'tone-neg' : j.status === 'late' ? 'tone-warn' : 'tone-mute',
            rank: false,
          }))),
    };
  },

  models(d) {
    return {
      flag: { dot: hFresh(d.age_h, 26, 72) },
      body: kpis([
        { l: t('home_k_live_pairs'), v: hNum(d.n_pairs), hero: true },
        { l: t('home_k_bots'), v: hNum(d.n_bots) },
        { l: t('home_k_dropped'), v: hNum(d.n_dropped), tone: d.n_dropped ? 'tone-warn' : '' },
      ], 3)
        + tsub(t('home_hdr_bots_30d'))
        + trows((d.bots || []).slice(0, 3).map(b => ({
            a: `<b>${hEsc(b.bot || '')}</b> <span class="b">${hEsc(b.exchange || '')} ${hEsc(b.timeframe || '')}</span>`,
            b: t('home_n_pairs', { n: hNum(b.n_pairs) }),
            c: hUsd(b.net_30d), tone: hTone(b.net_30d), rank: false,
          })))
        + tsub(t('home_hdr_worst_pairs'))
        + trows((d.worst_pairs || []).slice(0, 2).map(w => ({
            a: `<b>${hEsc(w.base || '')}</b> <span class="b">${hEsc(w.bot || '')}</span>`,
            b: w.action ? t('home_act_' + w.action) : '',
            c: hPct((w.avg_profit || 0) * 100, 1), tone: hTone(w.avg_profit), rank: false,
          })))
        + `<div class="tile-note">${t('home_models_feedback', {
            n: hNum(d.feedback_adjusted), q: hNum(d.retrain_queue) })}</div>`,
    };
  },

  logs(d) {
    const bad = d.n_errors > 0;
    return {
      flag: { dot: bad ? 'bad' : d.n_warnings > 0 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_errors'), v: hNum(d.n_errors), hero: true, tone: bad ? 'tone-neg' : 'tone-pos' },
        { l: t('home_k_warnings'), v: hNum(d.n_warnings), tone: d.n_warnings ? 'tone-warn' : '' },
        { l: t('home_k_lines'), v: hNum(d.n_lines) },
      ], 3)
        + svgBars(d.levels, { max: 5 })
        + tsub(t('home_hdr_problems'))
        + ((d.problems || []).length
            ? trows(d.problems.slice(0, 3).map(pr => ({
                a: `<b>${hEsc(pr.level)}</b> ${hEsc(pr.text)}`, rank: false })))
            : `<div class="tile-note">${t('home_logs_clean', { n: hNum(d.n_lines) })}</div>`)
        + `<div class="tile-note">${t('home_logs_window', { n: hNum(d.n_lines) })}</div>`,
    };
  },
};

/* `bybit_futures_BTCUSDT_1h.parquet` is too long for a table cell; the venue
   prefix is the part a reader can drop. */
function shortDs(name) {
  if (!name) return '';
  return String(name).replace(/\.parquet$/, '').split('_').slice(-2).join(' ');
}

// ═════════════════════════════════════════════════════════════ RENDER
function paintTile(host, key, data) {
  const r = (HOME_RENDER[key] || (() => ({ body: '', flag: {} })))(data || {});
  const flag = r.flag || {};
  const age = (data || {}).age_h;
  host.innerHTML = `
    <div class="tile-head">
      <div class="tile-glyph">${homeIcon(key)}</div>
      <div class="tile-id">
        <div class="n" title="${hEsc(t('sub_' + key))}">${hEsc(t('nav_' + key))}</div>
      </div>
      <div class="tile-flag">
        ${age != null ? `<span class="tile-age">${hAgo(age)}</span>` : ''}
        ${flag.chip ? `<span class="tile-chip">${hEsc(flag.chip)}</span>` : ''}
        ${flag.dot ? `<span class="tile-status ${flag.dot === 'muted' ? '' : flag.dot}"></span>` : ''}
      </div>
    </div>
    <div class="tile-body">${r.body}</div>`;
}

/* One continuous grid. Splitting it per group made every group wrap on its own
   and leave a ragged half-empty row behind it — grouping lives in the accent
   colour and the filter chips instead. */
function renderHome() {
  const wrap = document.getElementById('home-grid-host');
  if (!wrap) return;
  const d = homeState.data;
  const tiles = HOME_GROUPS.flatMap(g => g.tiles.map(k => ({ k, g: g.key })));

  wrap.innerHTML = `<div class="home-grid">${tiles.map(({ k, g }) => `
      <article class="tile${HOME_WIDE.has(k) ? ' lg' : ''}${d ? '' : ' skeleton'}"
        data-tile="${k}" data-group="${g}" style="--acc:${HOME_ACCENT[k]}"
        tabindex="0" role="button" aria-label="${hEsc(t('nav_' + k))}"
        onclick="showSection('${k}')"
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showSection('${k}')}">
        ${d ? '' : skeletonTile()}
      </article>`).join('')}</div>`;

  renderHomeFilter();
  applyHomeFilter();
  if (!d) return;
  wrap.querySelectorAll('.tile').forEach(el => {
    paintTile(el, el.dataset.tile, d.tiles[el.dataset.tile] || {});
  });
  renderHomeHero();
}

function skeletonTile() {
  return `<div class="tile-head">
      <div class="sk" style="width:28px;height:28px;border-radius:9px"></div>
      <div style="flex:1"><div class="sk" style="height:10px;width:52%"></div></div>
    </div>
    <div class="sk" style="height:22px;width:44%"></div>
    <div class="sk" style="height:6px;width:100%"></div>
    <div class="sk" style="height:6px;width:84%"></div>
    <div class="sk" style="height:6px;width:66%"></div>
    <div class="sk" style="height:6px;width:78%"></div>`;
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

function applyHomeFilter() {
  const cur = homeState.filter || 'all';
  document.querySelectorAll('#home-grid-host .tile').forEach(el => {
    el.classList.toggle('hidden', cur !== 'all' && el.dataset.group !== cur);
  });
}

/* The hero strip: the numbers worth seeing before any tile is read. */
function renderHomeHero() {
  const host = document.getElementById('home-hero-stats');
  if (!host || !homeState.data) return;
  const T = homeState.data.tiles;
  const fleet = T.fleet || {}, edges = T.edges || {}, pipe = T.pipeline || {},
        inv = T.inventory || {}, attr = T.attribution || {}, alt = T.altdata || {};
  const cells = [
    { l: t('home_k_equity'), v: hUsd(fleet.equity_usd) },
    { l: t('home_k_net'), v: hUsd(attr.net), tone: hTone(attr.net) },
    { l: t('home_k_gross_lev'), v: hNum(fleet.gross_leverage, 2) + '×' },
    { l: t('home_k_deployable'), v: hNum(edges.n_deployable), tone: 'tone-acc' },
    { l: t('home_k_jobs_ok'), v: `${hNum(pipe.ok)}/${hNum(pipe.n_jobs)}`,
      tone: (pipe.late || pipe.missing) ? 'tone-warn' : 'tone-pos' },
    { l: t('home_k_dvol_btc'), v: hNum(alt.dvol_btc, 1) },
    { l: t('home_k_datasets'), v: hNum(inv.n_datasets) },
  ];
  host.innerHTML = cells.map(c =>
    `<div class="hstat"><div class="l">${hEsc(c.l)}</div>
       <div class="v ${c.tone || ''}">${c.v}</div></div>`).join('');
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
    case 'report': return hSign(((d.best || {}).oos_sharpe), 1);
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
    quality: (T.quality || {}).stale_gt_3d > 200,
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
