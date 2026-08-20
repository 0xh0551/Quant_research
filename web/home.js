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

/* Strategy-family tints. `STRATEGY_TAGS` comes from i18n.js, which loads first;
   app.js's own colour map does not, and sibling classic scripts share one
   global lexical scope, so this cannot borrow it or redeclare its name. */
const HOME_FAMILY_TONE = { Trend: '#2dd4bf', MR: '#818cf8', ML: '#34d399' };

const homeState = { data: null, filter: 'all', timer: null, loading: false, error: null };

// ═════════════════════════════════════════════════════════════ FORMATTERS
/* Local escaper — app.js has its own `esc`, and two top-level consts of the
   same name in sibling classic scripts is a redeclaration error. */
const hEsc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Coerce first, then test: a string that is not a number must read as "—",
   not as "NaN%". */
const hFinite = v => { const n = Number(v); return v == null || v === '' || n !== n ? null : n; };

const hNum = (v, d = 0) => {
  const n = hFinite(v);
  return n == null ? '—'
    : n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
};

function hCompact(x) {
  const v = hFinite(x);
  if (v == null) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'K';
  return String(Math.round(v * 100) / 100);
}

/* Sign goes outside the symbol: `-$14.3`, never `$-14.3`. */
const hUsd = x => {
  const v = hFinite(x);
  return v == null ? '—' : (v < 0 ? '-$' : '$') + hCompact(Math.abs(v));
};
const hPct = (v, d = 1) => { const n = hFinite(v); return n == null ? '—' : n.toFixed(d) + '%'; };
const hSign = (v, d = 1) => {
  const n = hFinite(v);
  return n == null ? '—' : (n > 0 ? '+' : '') + n.toFixed(d);
};
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

// ═════════════════════════════════════════════════════════════ CHART VOCABULARY
/* One form per module. A dashboard where nineteen panels all draw the same
   four-bar chart teaches nothing — the shape of the graphic should say what
   kind of quantity it is before a single number is read. Each of these owns
   the leftover flex height, so they look right at any row size.

   coverage grid · stacked composition · ring · span · bullets · chips ·
   rank decay · funnel · lollipop · log strip · dumbbell · arc · treemap ·
   loss axis · waterfall · area · budget pips · slot grid · hour profile     */

/* Coverage grid — a category × category count matrix, ink by density. */
function cGrid(m) {
  const rows = (m || {}).venues || [], cols = (m || {}).timeframes || [], cells = (m || {}).cells || [];
  if (!rows.length || !cols.length) return `<div class="c-fill"></div>`;
  const peak = Math.max(...cells.flat(), 1);
  return `<div class="c-fill c-grid" style="grid-template-columns:auto repeat(${cols.length},1fr)">
    <span></span>${cols.map(c => `<span class="gh">${hEsc(c)}</span>`).join('')}
    ${rows.map((r, i) => `<span class="gr">${hEsc(r)}</span>` + cols.map((c, j) => {
      const v = (cells[i] || [])[j] || 0;
      return `<span class="gc" title="${hEsc(r)} · ${hEsc(c)}: ${hNum(v)}"
        style="opacity:${v ? (0.16 + 0.84 * Math.sqrt(v / peak)).toFixed(2) : 0.05}">${
        v ? `<i>${hCompact(v)}</i>` : ''}</span>`;
    }).join('')).join('')}
  </div>`;
}

/* Stacked composition — one bar that is the whole, split by share. */
function cStack(items, opts) {
  const o = Object.assign({ fmt: hCompact }, opts || {});
  const rows = (items || []).filter(r => r && r.v > 0);
  const total = rows.reduce((s, r) => s + r.v, 0);
  if (!total) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-stack">
    <div class="bar">${rows.map((r, i) => `
      <span style="flex:${r.v};opacity:${(1 - i * 0.17).toFixed(2)}"
            title="${hEsc(r.k)}: ${hEsc(String(o.fmt(r.v)))}"></span>`).join('')}</div>
    <div class="legend">${rows.map((r, i) => `
      <span><i style="opacity:${(1 - i * 0.17).toFixed(2)}"></i>${hEsc(r.k)}
        <b>${hEsc(String(o.fmt(r.v)))}</b></span>`).join('')}</div>
  </div>`;
}

/* Ring — one share of a whole, read as an angle. */
function cRing(pct, opts) {
  const o = Object.assign({ sub: '' }, opts || {});
  if (pct == null || pct !== pct) return `<div class="c-fill"></div>`;
  const R = 15.915494, C = 2 * Math.PI * R;
  return `<div class="c-fill c-ring">
    <svg viewBox="0 0 42 42">
      <circle cx="21" cy="21" r="${R}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="4"/>
      <circle cx="21" cy="21" r="${R}" fill="none" stroke="var(--acc)" stroke-width="4"
        stroke-linecap="round" stroke-dasharray="${(pct / 100 * C).toFixed(2)} ${C}"
        stroke-dashoffset="25" transform="rotate(-90 21 21)"/>
      <text x="21" y="21" text-anchor="middle" dominant-baseline="central"
        fill="var(--text)" font-size="9" font-weight="800">${Math.round(pct)}%</text>
      <text x="21" y="27.5" text-anchor="middle" dominant-baseline="central"
        fill="var(--text3)" font-size="3.6">${hEsc(o.sub)}</text>
    </svg></div>`;
}

/* Span — how much history there is, as a bar between two dates. */
function cSpan(from, to, opts) {
  const o = Object.assign({ mark: null, markLabel: '' }, opts || {});
  if (!from || !to) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-span">
    <div class="track">
      <span class="fill"></span>
      ${o.mark != null ? `<span class="mk" style="inset-inline-start:${
        Math.min(97, Math.max(1, o.mark * 100)).toFixed(1)}%" title="${hEsc(o.markLabel)}"></span>` : ''}
    </div>
    <div class="ends"><span>${hEsc(from)}</span><span>${hEsc(to)}</span></div>
  </div>`;
}

/* Bullets — small multiples of a 0..1 reading, for a regime panel. */
function cBullets(items) {
  const rows = (items || []).filter(r => r && r.v != null && r.v === r.v);
  if (!rows.length) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-bullets">${rows.map(r => `
    <div class="bl">
      <span class="k">${hEsc(t('home_b_' + r.k))}</span>
      <span class="track"><span class="fill" style="width:${(r.v * 100).toFixed(0)}%"></span>
        <i style="inset-inline-start:${(r.v * 100).toFixed(0)}%"></i></span>
      <span class="v">${(r.v * 100).toFixed(0)}</span>
    </div>`).join('')}</div>`;
}

/* Chips — a named palette, where the names are the information. */
function cChips(items, opts) {
  const o = Object.assign({ label: k => k, tone: () => 'var(--acc)' }, opts || {});
  const rows = items || [];
  if (!rows.length) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-chips">${rows.map(k => `
    <span class="chip" style="--t:${o.tone(k)}">${hEsc(o.label(k))}</span>`).join('')}</div>`;
}

/* Rank decay — a sorted series as thin columns; the fall-off is the point. */
function cDecay(vals, opts) {
  const o = Object.assign({ digits: 1 }, opts || {});
  const rows = (vals || []).filter(v => v != null && v === v);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const peak = Math.max(...rows.map(Math.abs)) || 1;
  return `<div class="c-fill c-decay">${rows.map((v, i) => `
    <span title="#${i + 1}: ${v.toFixed(o.digits)}"
      style="height:${Math.max(4, (Math.abs(v) / peak) * 100).toFixed(1)}%;
             opacity:${(1 - i / (rows.length * 1.5)).toFixed(2)}"></span>`).join('')}</div>`;
}

/* Funnel — a survival cascade, each stage a share of the one above. */
function cFunnel(stages) {
  const rows = (stages || []).filter(r => r && r.v != null);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const peak = Math.max(...rows.map(r => r.v)) || 1;
  return `<div class="c-fill c-funnel">${rows.map((r, i) => `
    <div class="fs" title="${hEsc(t('home_f_' + r.k))}: ${hNum(r.v)}">
      <span class="band" style="width:${Math.max(6, Math.sqrt(r.v / peak) * 100).toFixed(1)}%;
        opacity:${(1 - i * 0.16).toFixed(2)}"></span>
      <span class="lb">${hEsc(t('home_f_' + r.k))}</span>
      <span class="vv">${hCompact(r.v)}</span>
    </div>`).join('')}</div>`;
}

/* Lollipop — a ranked small set where the value is a position, not an area. */
function cLollipop(items, opts) {
  const o = Object.assign({ fmt: v => hPct(v, 0), label: k => k }, opts || {});
  const rows = (items || []).filter(r => r && r.v != null);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const peak = Math.max(...rows.map(r => r.v)) || 1;
  return `<div class="c-fill c-lolli">${rows.map(r => `
    <div class="lp" title="${hEsc(o.label(r.k))}: ${hEsc(String(o.fmt(r.v)))}">
      <span class="k">${hEsc(o.label(r.k))}</span>
      <span class="line"><i style="inset-inline-start:${(r.v / peak * 100).toFixed(1)}%"></i>
        <u style="width:${(r.v / peak * 100).toFixed(1)}%"></u></span>
      <span class="v">${hEsc(String(o.fmt(r.v)))}</span>
    </div>`).join('')}</div>`;
}

/* Log strip — every item as a dot on a decade axis; clustering is the signal. */
function cLogStrip(points, opts) {
  const o = Object.assign({ fmt: hUsd }, opts || {});
  const rows = (points || []).filter(p => p && p.v > 0);
  if (rows.length < 2) return `<div class="c-fill"></div>`;
  const ls = rows.map(p => Math.log10(p.v));
  const lo = Math.floor(Math.min(...ls)), hi = Math.ceil(Math.max(...ls));
  const span = (hi - lo) || 1;
  const ticks = [];
  for (let d = lo; d <= hi; d++) ticks.push(d);
  return `<div class="c-fill c-strip">
    <div class="axis">
      ${ticks.map(d => `<span class="dec" style="inset-inline-start:${
        ((d - lo) / span * 100).toFixed(1)}%"></span>`).join('')}
      ${rows.map(p => `<span class="pt" title="${hEsc(p.k || '')}: ${hEsc(String(o.fmt(p.v)))}"
        style="inset-inline-start:${((Math.log10(p.v) - lo) / span * 100).toFixed(1)}%"></span>`).join('')}
    </div>
    <div class="ends"><span>${hEsc(String(o.fmt(Math.pow(10, lo))))}</span>
      <span>${hEsc(String(o.fmt(Math.pow(10, hi))))}</span></div>
  </div>`;
}

/* Dumbbell — two legs of a spread and the gap between them. */
function cDumbbell(items, opts) {
  const o = Object.assign({ fmt: v => hPct(v, 0) }, opts || {});
  const rows = (items || []).filter(r => r && r.a != null && r.b != null);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const all = rows.flatMap(r => [r.a, r.b]);
  const lo = Math.min(...all), hi = Math.max(...all), span = (hi - lo) || 1;
  const at = v => (((v - lo) / span) * 92 + 4).toFixed(1);
  return `<div class="c-fill c-dumb">${rows.map(r => `
    <div class="db" title="${hEsc(r.k)}: ${hEsc(String(o.fmt(r.a)))} → ${hEsc(String(o.fmt(r.b)))}">
      <span class="k">${hEsc(r.k)}</span>
      <span class="rail">
        <u style="inset-inline-start:${Math.min(at(r.a), at(r.b))}%;
                  width:${Math.abs(at(r.a) - at(r.b)).toFixed(1)}%"></u>
        <i class="a" style="inset-inline-start:${at(r.a)}%"></i>
        <i class="b" style="inset-inline-start:${at(r.b)}%"></i>
      </span>
      <span class="v">${hEsc(String(o.fmt(r.gap)))}</span>
    </div>`).join('')}</div>`;
}

/* Arc — one value read against the ceiling it must not cross. */
function cArc(value, max, opts) {
  const o = Object.assign({ label: '', sub: '', tone: 'var(--acc)' }, opts || {});
  if (value == null || !max) return `<div class="c-fill"></div>`;
  const f = Math.min(1, Math.max(0, value / max));
  const R = 26, CX = 32, CY = 30;
  const pt = a => [CX + R * Math.cos(a), CY + R * Math.sin(a)];
  const a0 = Math.PI * 0.82, a1 = Math.PI * 2.18;          // open-bottom arc
  const [sx, sy] = pt(a0), [ex, ey] = pt(a1);
  const [vx, vy] = pt(a0 + (a1 - a0) * f);
  const big = (a1 - a0) * f > Math.PI ? 1 : 0;
  return `<div class="c-fill c-arc">
    <svg viewBox="0 0 64 52">
      <path d="M${sx.toFixed(1)},${sy.toFixed(1)} A${R},${R} 0 1,1 ${ex.toFixed(1)},${ey.toFixed(1)}"
            fill="none" stroke="rgba(255,255,255,.07)" stroke-width="5" stroke-linecap="round"/>
      <path d="M${sx.toFixed(1)},${sy.toFixed(1)} A${R},${R} 0 ${big},1 ${vx.toFixed(1)},${vy.toFixed(1)}"
            fill="none" stroke="${o.tone}" stroke-width="5" stroke-linecap="round"/>
      <text x="32" y="30" text-anchor="middle" dominant-baseline="central"
            fill="var(--text)" font-size="13" font-weight="800">${hEsc(o.label)}</text>
      <text x="32" y="40" text-anchor="middle" dominant-baseline="central"
            fill="var(--text3)" font-size="5">${hEsc(o.sub)}</text>
    </svg></div>`;
}

/* Treemap — weights as areas, by recursive slice-and-dice. */
function cTreemap(items) {
  const rows = (items || []).filter(r => r && r.pct > 0).slice(0, 7);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const build = (list, horiz) => {
    if (list.length === 1) {
      const r = list[0];
      return `<div class="tm" style="flex:${r.pct};opacity:${(0.35 + 0.6 * (r.pct / rows[0].pct)).toFixed(2)}"
        title="${hEsc(r.k)}: ${r.pct}%"><b>${hEsc(r.k)}</b><i>${Math.round(r.pct)}</i></div>`;
    }
    // split so the two halves carry as close to equal weight as possible
    const total = list.reduce((s, r) => s + r.pct, 0);
    let acc = 0, cut = 1;
    for (let i = 0; i < list.length - 1; i++) {
      acc += list[i].pct;
      if (acc >= total / 2) { cut = i + 1; break; }
      cut = i + 2;
    }
    const a = list.slice(0, cut), b = list.slice(cut);
    const w = x => x.reduce((s, r) => s + r.pct, 0);
    return `<div class="tmg" style="flex:${total};flex-direction:${horiz ? 'row' : 'column'}">
      <div class="tmg" style="flex:${w(a)};flex-direction:${horiz ? 'column' : 'row'}">${build(a, !horiz)}</div>
      <div class="tmg" style="flex:${w(b)};flex-direction:${horiz ? 'column' : 'row'}">${build(b, !horiz)}</div>
    </div>`;
  };
  return `<div class="c-fill c-tree">${build(rows, true)}</div>`;
}

/* Loss axis — every scenario placed on one signed % track. */
function cLossAxis(ticks, opts) {
  const o = Object.assign({ worst: null }, opts || {});
  const rows = (ticks || []).filter(r => r && r.v != null);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const lim = Math.max(0.1, ...rows.map(r => Math.abs(r.v)));
  const at = v => (50 + (v / lim) * 46).toFixed(1);
  return `<div class="c-fill c-loss">
    <div class="rail">
      <span class="zero"></span>
      ${rows.map(r => `<span class="tk ${r.v < 0 ? 'neg' : 'pos'}${r.k === o.worst ? ' w' : ''}"
        style="inset-inline-start:${at(r.v)}%" title="${hEsc(r.k)}: ${hSign(r.v, 2)}%"></span>`).join('')}
    </div>
    <div class="ends"><span>${hSign(-lim, 1)}%</span><span>0</span><span>${hSign(lim, 1)}%</span></div>
  </div>`;
}

/* Waterfall — a bridge from the first quantity to the last. */
function cWaterfall(steps, opts) {
  const o = Object.assign({ net: null, fmt: v => hSign(v, 0) }, opts || {});
  const rows = (steps || []).filter(r => r && r.v != null && r.v === r.v);
  if (!rows.length) return `<div class="c-fill"></div>`;
  let run = 0;
  const bars = rows.map(r => { const from = run; run += r.v; return { ...r, from, to: run }; });
  const lo = Math.min(0, ...bars.map(b => Math.min(b.from, b.to)));
  const hi = Math.max(0, ...bars.map(b => Math.max(b.from, b.to)));
  const span = (hi - lo) || 1;
  const y = v => (100 - ((v - lo) / span) * 100);
  return `<div class="c-fill c-wf">
    <div class="plot">
      <span class="base" style="top:${y(0).toFixed(1)}%"></span>
      ${bars.map(b => `<span class="wb ${b.v >= 0 ? 'pos' : 'neg'}"
        title="${hEsc(t('home_a_' + b.k))}: ${hEsc(String(o.fmt(b.v)))}"
        style="top:${y(Math.max(b.from, b.to)).toFixed(1)}%;
               height:${Math.max(1.5, Math.abs(y(b.to) - y(b.from))).toFixed(1)}%"></span>`).join('')}
      ${o.net != null ? `<span class="wb net" title="${hEsc(t('home_k_net'))}: ${hUsd(o.net)}"
        style="top:${Math.min(y(0), y(o.net)).toFixed(1)}%;
               height:${Math.max(1.5, Math.abs(y(o.net) - y(0))).toFixed(1)}%"></span>` : ''}
    </div>
    <div class="keys">${bars.map(b => `<span>${hEsc(t('home_a_' + b.k))}</span>`).join('')}
      ${o.net != null ? `<span class="n">${hEsc(t('home_k_net'))}</span>` : ''}</div>
  </div>`;
}

/* Area — a genuine time series, with a hover readout. */
function cArea(vals, opts) {
  const o = Object.assign({ digits: 1, unit: '' }, opts || {});
  const clean = (vals || []).filter(v => v != null && v === v);
  if (clean.length < 2) return `<div class="c-fill"></div>`;
  const W = 100, H = 40;
  const lo = Math.min(...clean), hi = Math.max(...clean), span = hi - lo || 1;
  const x = i => (i / (clean.length - 1)) * W;
  const y = v => H - 3 - ((v - lo) / span) * (H - 9);
  const line = clean.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join('');
  const id = 'a' + Math.random().toString(36).slice(2, 8);
  const last = clean[clean.length - 1];
  return `<div class="c-fill c-area" data-vals="${clean.join(',')}" data-digits="${o.digits}"
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
    </svg></div>`;
}

function homeSparkMove(ev, el) {
  const vals = el.dataset.vals.split(',').map(Number);
  const r = el.getBoundingClientRect();
  // SVG user space is always left-to-right — CSS `direction` does not mirror it,
  // so the pointer maps straight onto the index in both FA and EN.
  const i = Math.min(vals.length - 1, Math.max(0,
    Math.round(((ev.clientX - r.left) / r.width) * (vals.length - 1))));
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

/* Budget pips — one pip per scheduled job, filled by how much of its own
   freshness budget is spent. */
function cBudgetPips(jobs) {
  const rows = (jobs || []).filter(j => j && j.k);
  if (!rows.length) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-pips">${rows.map(j => {
    const u = Math.min(1, j.used == null ? 0 : j.used);
    const tone = j.status === 'missing' ? 'bad' : j.status === 'late' ? 'warn' : 'ok';
    return `<span class="pip ${tone}" title="${hEsc(j.k)} — ${hEsc(t('pipe_s_' + (j.status || 'ok')))}">
      <i style="height:${(u * 100).toFixed(0)}%"></i></span>`;
  }).join('')}</div>`;
}

/* Slot grid — one cell per allocated unit, grouped and tinted by owner. */
function cSlots(groups, opts) {
  const o = Object.assign({ tone: () => 'var(--acc)' }, opts || {});
  const rows = (groups || []).filter(g => g && g.v > 0);
  if (!rows.length) return `<div class="c-fill"></div>`;
  return `<div class="c-fill c-slots">${rows.map(g => `
    <div class="sg" title="${hEsc(g.k)}: ${hNum(g.v)}">
      <div class="cells">${Array.from({ length: Math.min(12, g.v) }, () =>
        `<span style="background:${o.tone(g)}"></span>`).join('')}</div>
      <span class="k">${hEsc(g.k)}</span>
    </div>`).join('')}</div>`;
}

/* Hour profile — activity per hour over the last day. */
function cHours(vals) {
  const rows = (vals || []).filter(v => v != null);
  if (!rows.length) return `<div class="c-fill"></div>`;
  const peak = Math.max(...rows) || 1;
  return `<div class="c-fill c-hours">${rows.map((v, i) => `
    <span title="${t('home_h_ago', { n: rows.length - i })}: ${hNum(v)}"
      style="height:${Math.max(3, (v / peak) * 100).toFixed(1)}%"></span>`).join('')}</div>`;
}

function kpis(items) {
  return `<div class="kpis${items.length === 2 ? ' c2' : ''}">${items.map(k => `
    <div class="kpi${k.hero ? ' hero' : ''}">
      <div class="l" title="${hEsc(k.l)}">${hEsc(k.l)}</div>
      <div class="v ${k.tone || ''}">${k.v}${k.u ? `<span class="u">${hEsc(k.u)}</span>` : ''}</div>
    </div>`).join('')}</div>`;
}

// ═════════════════════════════════════════════════════════════ TILE BODIES
/* Three numbers and the one graphic that fits what this module measures.
   Every renderer must survive an empty payload: on a fresh install none of the
   artifacts exist yet. */
const HOME_RENDER = {

  /* Coverage of the store: which venue carries which timeframes. */
  inventory(d) {
    return {
      flag: {},
      body: kpis([
        { l: t('home_k_datasets'), v: hNum(d.n_datasets), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_size'), v: hNum(d.total_gb, 1), u: 'GB' },
      ]) + cGrid(d.matrix),
    };
  },

  /* Freshness of the store, as a composition of age buckets. */
  download(d) {
    return {
      flag: { dot: hFresh(d.newest_age_h, 12, 48) },
      body: kpis([
        { l: t('home_k_newest'), v: hAgo(d.newest_age_h), hero: true, tone: 'tone-acc' },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
        { l: t('home_k_datasets'), v: hCompact(d.n_datasets) },
      ]) + cStack(d.recency),
    };
  },

  /* How much of the store is long enough to walk forward on. */
  quality(d) {
    const pct = d.scannable_pct;
    return {
      flag: { dot: pct == null ? 'muted' : pct >= 60 ? 'ok' : pct >= 40 ? 'warn' : 'bad' },
      body: kpis([
        { l: t('home_k_median_bars'), v: hCompact(d.median_bars), hero: true },
        { l: t('home_k_stale3d'), v: hNum(d.stale_gt_3d), tone: d.stale_gt_3d ? 'tone-warn' : '' },
      ]) + cRing(pct, { sub: t('home_k_scannable') }),
    };
  },

  /* How far back a backtest can reach. */
  research(d) {
    const span = d.median_span_days, max = d.max_span_days;
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_median_span'), v: hNum(span == null ? null : span / 365, 1), u: t('home_u_yr'), hero: true },
        { l: t('home_k_symbols'), v: hNum(d.n_symbols) },
        { l: t('home_k_runs'), v: hNum(d.n_runs) },
      ]) + cSpan(d.first, d.last, {
        mark: (span && max) ? span / max : null, markLabel: t('home_k_median_span'),
      }),
    };
  },

  /* The three regime readings the strategy picker is conditioned on. */
  insights(d) {
    const risk = ((d.gauges || [])[0] || {}).v;
    return {
      flag: { chip: t('home_chip_tool'),
              dot: risk == null ? '' : risk > 0.5 ? 'bad' : risk > 0.3 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1), hero: true, tone: 'tone-acc' },
        { l: t('home_k_ls'), v: hNum(d.ls_ratio_btc, 2),
          tone: d.ls_ratio_btc > 1 ? 'tone-pos' : 'tone-neg' },
        { l: t('home_k_watched'), v: hNum(d.n_event_symbols) },
      ]) + cBullets(d.gauges),
    };
  },

  /* The palette the optimiser can be pointed at. */
  lab(d) {
    return {
      flag: { chip: t('home_chip_tool') },
      body: kpis([
        { l: t('home_k_strategies'), v: hNum(d.n_strategies), hero: true },
        { l: t('home_k_params'), v: hNum(d.n_params) },
      ]) + cChips(d.strategies, {
        label: k => (STRATEGY_LABELS[k] || k),
        tone: k => (HOME_FAMILY_TONE[String(STRATEGY_TAGS[k] || '').split(' ')[0]] || 'var(--acc)'),
      }),
    };
  },

  /* How fast OOS quality falls away from the best edge. */
  report(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_best_sharpe'), v: hSign(d.best_sharpe, 1), hero: true, tone: hTone(d.best_sharpe) },
        { l: t('home_k_oos_ret'), v: d.best_return == null ? '—' : hPct(d.best_return * 100, 0),
          tone: hTone(d.best_return) },
        { l: t('home_k_ranked'), v: hNum(d.n_top) },
      ]) + cDecay(d.sharpes, { digits: 1 }),
    };
  },

  /* The scan funnel, candidate to deployable. */
  edges(d) {
    const deployable = ((d.funnel || []).find(f => f.k === 'deployable') || {}).v;
    return {
      flag: { dot: hFresh(d.age_h, 30, 72), chip: d.live_timeframe || '' },
      body: kpis([
        { l: t('home_k_deployable'), v: hNum(deployable), hero: true, tone: 'tone-acc' },
        { l: t('home_k_pbo'), v: hPct((d.median_pbo || 0) * 100, 0),
          tone: d.median_pbo > 0.5 ? 'tone-neg' : d.median_pbo > 0.35 ? 'tone-warn' : 'tone-pos' },
      ]) + cFunnel(d.funnel),
    };
  },

  /* Which strategy families clear the bar, once every trial is counted. */
  trials(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_unique'), v: hCompact(d.n_unique), hero: true },
        { l: t('home_k_pass_rate'), v: hPct(d.pass_rate, 1), tone: 'tone-acc' },
        { l: t('home_k_deflated'), v: hNum(d.n_deflated_pass),
          tone: d.n_deflated_pass ? 'tone-pos' : 'tone-warn' },
      ]) + cLollipop(d.strategies, { label: k => (STRATEGY_LABELS[k] || k) }),
    };
  },

  /* Where the live edges sit on a decade axis of tradable size. */
  capacity(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_median_cap'), v: hUsd(d.median_capacity), hero: true },
        { l: t('home_k_tightest'), v: hUsd(d.min_capacity), tone: 'tone-warn' },
        { l: t('home_k_books'), v: hNum(d.n_books) },
      ]) + cLogStrip(d.points),
    };
  },

  /* Both legs of the best funding spreads, and the gap that is the trade. */
  crossex(d) {
    return {
      flag: { chip: 'α', dot: hFresh(d.carry_age_h, 8, 26) },
      body: kpis([
        { l: t('home_k_best_carry'), v: hPct(d.best_spread, 0), hero: true, tone: 'tone-acc' },
        { l: t('home_k_multivenue'), v: hNum(d.multi_venue_symbols) },
        { l: t('home_k_venues'), v: hNum(d.n_venues) },
      ]) + cDumbbell((d.carry || []).map(c => ({ k: c.base, a: c.long, b: c.short, gap: c.spread }))),
    };
  },

  /* Leverage read against the ceiling it must not cross. */
  fleet(d) {
    const f = d.max_gross_leverage ? (d.gross_leverage / d.max_gross_leverage) : 0;
    return {
      flag: { dot: d.n_alerts > 0 ? 'bad' : hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_equity'), v: hUsd(d.equity_usd), hero: true },
        { l: t('home_k_net_delta'), v: hSign(d.net_beta_delta_pct, 1), u: '%',
          tone: hTone(d.net_beta_delta_pct) },
        { l: t('home_k_positions'), v: hNum(d.n_positions) },
      ]) + cArc(d.gross_leverage, d.max_gross_leverage, {
        label: hNum(d.gross_leverage, 2) + '×',
        sub: t('home_fleet_cap', { n: hNum(d.max_gross_leverage, 1) }),
        tone: f > 0.8 ? 'var(--red)' : f > 0.5 ? 'var(--yellow)' : 'var(--acc)',
      }),
    };
  },

  /* The open book as areas — concentration you can see without reading. */
  portfolio(d) {
    return {
      flag: { dot: hFresh(d.age_h, 6, 24) },
      body: kpis([
        { l: t('home_k_book'), v: hUsd(d.gross_usd), hero: true },
        { l: t('home_k_hhi'), v: hNum(d.hhi, 2), tone: d.hhi > 0.3 ? 'tone-warn' : 'tone-pos' },
        { l: t('home_k_assets_n'), v: hNum(d.n_assets) },
      ]) + cTreemap((d.top || []).map(a => ({ k: a.base, pct: a.pct }))),
    };
  },

  /* Every scenario's hit, placed on one signed equity axis. */
  stress(d) {
    return {
      flag: { dot: d.n_liquidations > 0 ? 'bad' : hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_worst_loss'), v: hSign(d.worst_pct, 2), u: '%', hero: true,
          tone: hTone(d.worst_pct) },
        { l: t('home_k_scenarios'), v: hNum(d.n_scenarios) },
        { l: t('home_k_liquidations'), v: hNum(d.n_liquidations),
          tone: d.n_liquidations ? 'tone-neg' : 'tone-pos' },
      ]) + cLossAxis(d.ticks, { worst: d.worst_key }),
    };
  },

  /* The bridge from intended alpha to what actually landed. */
  attribution(d) {
    return {
      flag: { dot: hFresh(d.age_h, 30, 72) },
      body: kpis([
        { l: t('home_k_net'), v: hUsd(d.net), hero: true, tone: hTone(d.net) },
        { l: t('home_k_intended'), v: hUsd(((d.steps || [])[0] || {}).v),
          tone: hTone(((d.steps || [])[0] || {}).v) },
        { l: t('home_k_window'), v: hNum(d.window_days), u: t('home_u_d') },
      ]) + cWaterfall(d.steps, { net: d.net, fmt: v => hSign(v, 0) }),
    };
  },

  /* Implied vol, as the track behind today's reading. */
  altdata(d) {
    return {
      flag: { dot: hFresh(d.age_h, 8, 24) },
      body: kpis([
        { l: t('home_k_dvol_btc'), v: hNum(d.dvol_btc, 1), hero: true, tone: 'tone-acc' },
        { l: t('home_k_dvol_eth'), v: hNum(d.dvol_eth, 1) },
        { l: t('home_k_liq24'), v: hUsd(d.liquidations_24h_usd) },
      ]) + cArea(d.dvol_series, { digits: 1 }),
    };
  },

  /* One pip per job, filled by how much of its freshness budget is spent. */
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
      ]) + cBudgetPips(d.jobs),
    };
  },

  /* How the live pair budget is split across the bots. */
  models(d) {
    return {
      flag: { dot: hFresh(d.age_h, 26, 72) },
      body: kpis([
        { l: t('home_k_live_pairs'), v: hNum(d.n_pairs), hero: true },
        { l: t('home_k_bots'), v: hNum(d.n_bots) },
        { l: t('home_k_dropped'), v: hNum(d.n_dropped), tone: d.n_dropped ? 'tone-warn' : '' },
      ]) + cSlots(d.split, {
        tone: g => (g.net == null ? 'var(--acc)' : g.net >= 0 ? 'var(--green)' : 'var(--red)'),
      }),
    };
  },

  /* Hourly chatter — a silent service and a screaming one both show here. */
  logs(d) {
    const bad = d.n_errors > 0;
    return {
      flag: { dot: bad ? 'bad' : d.n_warnings > 0 ? 'warn' : 'ok' },
      body: kpis([
        { l: t('home_k_errors'), v: hNum(d.n_errors), hero: true, tone: bad ? 'tone-neg' : 'tone-pos' },
        { l: t('home_k_warnings'), v: hNum(d.n_warnings), tone: d.n_warnings ? 'tone-warn' : '' },
        { l: t('home_k_lines'), v: hCompact(d.n_lines) },
      ]) + cHours(d.hourly),
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
    case 'download': return hAgo(d.newest_age_h);
    case 'quality': return hPct(d.scannable_pct, 0);
    case 'research': return d.n_runs ? hCompact(d.n_runs) : '';
    case 'report': return hSign(d.best_sharpe, 1);
    case 'insights': return hNum(((d.gauges || [])[0] || {}).v, 2);
    case 'lab': return hNum(d.n_strategies);
    case 'edges': return hNum(((d.funnel || []).find(f => f.k === 'deployable') || {}).v);
    case 'trials': return hPct(d.pass_rate, 1);
    case 'capacity': return hUsd(d.median_capacity);
    case 'crossex': return hPct(d.best_spread, 0);
    case 'fleet': return hNum(d.gross_leverage, 2) + '×';
    case 'portfolio': return hUsd(d.gross_usd);
    case 'stress': return hSign(d.worst_pct, 1) + '%';
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
