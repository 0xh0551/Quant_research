# Changelog

## [1.5.2] — 2026-08-20

### Uniform tiles, bigger type

- **Every tile is now the same height.** `grid-auto-rows: 340px` with the body
  clipping instead of pushing, so the wall reads as a grid rather than a ragged
  column stack. To make that honest rather than a crop, each tile's content was
  measured against the budget and retuned: the two wide tiles (edges, fleet) put
  their chart beside their table instead of stacking them, and the eight tiles
  that came in short gained a real block — stalest datasets on data quality, run
  kinds on research, the store's timeframe mix on lab, venue coverage on
  cross-exchange, a loss-spread chart on stress, top-edge timeframes on
  insights, entry slippage and a fifth bot on attribution. Every tile now lands
  between 286 px and 331 px in a 340 px row, in both languages. Below 760 px the
  rows go back to auto so nothing clips on a phone.
- **Type went up a step throughout**: KPI values 16→20 px (hero 21→26), table
  rows 10.5→12, bar labels 10→11.5, captions 9→10.5, tile titles 12.5→14, and
  the sidebar 11.5→12.5 at 186 px wide. Column minimum widened to 272 px to
  match.

## [1.5.1] — 2026-08-20

### Denser wall, and a sidebar you can actually read

- **One continuous grid** instead of a grid per group. Five separate grids each
  wrapped on their own and left a ragged half-empty row behind them; grouping
  now lives in the accent colour plus a row of filter chips that also act as the
  legend. Gutters, paddings and type all came down a step.
- **Every tile carries more.** New backend reads feed them: walk-forward scan
  history (`wf_history.jsonl`) and pipeline health history as trend sparklines,
  the 30-day go-live scorecard folded into the fleet and models rows, funding
  carry as the cross-exchange leaderboard, per-strategy pass rates, per-bot
  execution drag, tightest-capacity edges, funding extremes, dataset-length
  histogram, recent experiment runs, the actual late/missing job list, and the
  last log problems. 272 readable data points across the wall, up from ~90.
- **The sidebar is labelled again.** An icon-only rail of nineteen sections was
  a guessing game. It is now a 172 px grouped menu where every row carries its
  name *and* that section's headline number (deployable edges, gross leverage,
  jobs healthy, error count…), collapsible to icons with the choice remembered.
- Sign now sits outside the currency symbol (`-$14.3`), rotation action codes
  are translated rather than leaked raw, and narrow tiles lay their KPIs out in
  two rows instead of four squeezed columns.

## [1.5.0] — 2026-08-20

### Home screen: the menu becomes a wall of live widgets

The dashboard had grown to nineteen sections behind one long labelled sidebar —
a list you had to read top to bottom to find anything, and which said nothing
about the state of what it linked to. That list is gone.

- **Launcher grid** (`web/home.js`, new default view). Every section is a tile
  laid out like a phone home screen: equal gutters, squircle app glyph, two
  widget widths. A tile is a *widget*, not a link — it carries that section's
  own KPIs, a micro-chart, and controls that work inside the card:
  - segmented toggles that repaint a tile without a refetch (inventory by
    timeframe/venue, edges passed/robust, fleet leverage/open/PnL),
  - sparklines with a live hover readout (top-20 OOS Sharpe, BTC DVOL series),
  - bar, diverging-bar, funnel, donut and meter charts, all hand-rolled inline
    SVG — nineteen Plotly instances on the landing view would have cost more
    than the rest of the dashboard put together,
  - freshness dot per tile, and a hero strip with fleet equity, deployable
    edges, job health and dataset count.
- **`GET /api/home/summary`** (`src/web/home.py`). One TTL-cached call feeds all
  nineteen widgets. It reads only artifacts other jobs already wrote plus a
  `stat()` sweep of the parquet store — never a backtest, a parquet parse or an
  exchange round-trip — so the landing view costs ~0.2 s warm. A missing or
  corrupt artifact blanks one tile, never the grid.
- **Icon rail** replaces the sidebar: 66 px, grouped, tooltipped, with red dots
  for fleet alerts / failing pipeline jobs / log errors.
- **Command palette** (`Ctrl/⌘+K`) matches on the FA name, the EN name or the
  section key, so either language finds the same section.
- Tiles, rail and palette are keyboard-operable and fully bilingual; the FA/EN
  guard now covers `home.js` and asserts every section has a tile and every tile
  a renderer.

## [1.3.0] — 2026-06-11

### Quant rigor, cross-exchange alpha, portfolio, ML/RL, MLOps

A professional-grade upgrade addressing the platform's biggest gaps. New Python
modules are pure/tested; the user-facing ones are wired into four new dashboard
sections (fully bilingual). Optional accelerators (`optuna`, `mlflow`,
`gymnasium`, `stable-baselines3`) are import-guarded — everything degrades
gracefully without them. Dashboard font switched to **Vazirmatn**.

#### Tier 0 — statistical rigor (selection-bias defences)
- `src/analysis/statistics.py`: **Probabilistic** & **Deflated Sharpe Ratio**
  (Bailey & López de Prado), **moving-block bootstrap CIs**, and **CSCV PBO**
  (Probability of Backtest Overfitting).
- The walk-forward scan (`wf_scan.py`) now reports `psr`, `dsr`, `pbo`,
  `sharpe_ci_*` and `deflated_pass` per candidate + a dataset-level `rigor`
  summary — surfaced as new columns and a rigor card in the **Edges** section.
- `src/ml/labeling.py` (triple-barrier + meta-labels) and `src/ml/cv.py`
  (**PurgedKFold** + embargo, purged walk-forward) fix the leakage in the
  single-bar ML labels.
- Report metrics table now shows a bootstrap **Sharpe 95% CI** row.

#### Tier 1 — cross-exchange suite (new **Cross-Exchange** section)
- `src/analysis/cross_exchange.py`: **lead-lag**, **cointegration** (Engle-Granger
  + hedge ratio), **basis** (perp-vs-spot), and **liquidity** comparison across
  every venue holding the same symbol.
- `src/data/funding.py`: funding-rate / open-interest ingestion via CCXT.

#### Tier 2 — portfolio & risk (new **Portfolio** section)
- `src/portfolio/`: vol-targeting + **fractional Kelly** sizing, **HRP** /
  risk-parity / inverse-vol construction, and a risk overlay (drawdown control,
  regime gate, square-root **capacity** model).
- Backtest engine gains a realistic cost model: explicit **taker fee** and a
  **volatility/liquidity-aware dynamic slippage** model (`slippage_model="dynamic"`),
  on top of the existing perpetual-funding accrual.

#### Tier 3 — real ML/RL (new **Models** section)
- `src/ml/model_eval.py`: honest **purged-CV AUC** (triple-barrier labels) that
  replaces the heuristic "ML fitness", with optional **Optuna** tuning.
- `src/rl/env.py`: a gym-style trading env whose reward nets fees + funding;
  `src/rl/recommend.py`: ranks the best **RL coins on 15m futures (Bybit/OKX/Gate)**.

#### Tier 4 — MLOps (new **Data Quality** section + CI)
- `src/tracking/experiments.py`: file-based experiment ledger (+ optional MLflow),
  global seeding and dataset fingerprinting for reproducibility.
- `src/analysis/forward_test.py`: expected-vs-realized attribution from the live
  bots' freqtrade DBs, with divergence alerts.
- `src/validation/monitor.py`: fleet-wide data-quality health report.
- `.github/workflows/scheduled-research.yml`: nightly data refresh + edge scan,
  publishing reports as artifacts.

### API Endpoints Added
| Endpoint | Method | Description |
|---|---|---|
| `/api/cross-exchange/symbols` | GET | Symbols available on ≥2 venues |
| `/api/cross-exchange` | GET | Lead-lag / cointegration / basis / liquidity for a symbol |
| `/api/portfolio` | POST | HRP/risk-parity weights + Kelly/vol-target sizing |
| `/api/ml/evaluate` | POST | Purged-CV AUC for a dataset (optional Optuna tuning) |
| `/api/rl/recommend` | GET | Best RL coins on 15m futures (Bybit/OKX/Gate) |
| `/api/quality` | GET | Fleet-wide data-quality report |
| `/api/forward-test` | GET | Expected-vs-realized PnL attribution |
| `/api/experiments` | GET | Recent experiment-ledger runs |

## [1.2.0] — 2026-06-11

### UI redesign — "Midnight Aurora" + full bilingual support

#### Unified, consistent layout
- **Edges is now a section of the single-page dashboard** (sidebar + topbar like every other tab) instead of a separate full-screen page. The old `/edges` URL still works — it serves the SPA and deep-links to the Edges section on boot.
- Edges charts re-implemented in **Plotly** (was Chart.js) so the whole app uses one charting engine and one visual language.
- New **Midnight Aurora** theme: deep slate-indigo canvas, teal-emerald primary, soft-violet accent, amber alerts. Added hover lifts, smooth section transitions, a glass top bar, and an aurora-gradient brand mark.

#### Real internationalization (FA / EN)
- New `web/i18n.js`: a single `I18N` dictionary (264 keys × 2 languages, full parity) with `t()`, `applyI18n()`, and `setLang()`. **Switching to English now translates every string** — static markup (`data-i18n*` attributes) and all JS-rendered content — with **zero Persian leaking** (verified across all sections).
- Layout is fully bidirectional via CSS **logical properties**, so toggling language flips RTL↔LTR correctly (sidebar side, borders, alignment).
- **Backend emits language-neutral codes**, not display text: recommendation reasons, regime labels, ML/RL hints, and job progress messages are now `{code, params}` resolved on the client. Edge alerts render from their structured fields.

#### Install-time language selection
- `scripts/setup.sh` (and `make setup`) installs dependencies and **prompts for the default dashboard language**, persisting it to `configs/app.json`.
- New `GET /api/config` serves the default language; the frontend resolves language as: explicit user toggle (localStorage) → install default → `fa`.
- `make lang` re-runs just the language picker.

#### Refactor
- The 2,543-line monolithic `dashboard.html` was split into `dashboard.html` (shell) + `styles.css` + `i18n.js` + `app.js`, served as prefix-aware relative static assets (works behind the `/admin/quant/` reverse proxy).
- `web/edges.html` removed (folded into the SPA).

### API Endpoints Added
| Endpoint | Method | Description |
|---|---|---|
| `/api/config` | GET | Returns the install-time default dashboard language |

## [1.1.0] — 2026-06-06

### Added

#### Futures: Full Long/Short Support
- `BacktestConfig.allow_short` flag enables `-1/0/+1` position signals
- Auto-detected from filename: datasets with `futures`/`perp`/`um`/`cm` in the name automatically enable short positions
- All 14 strategies support symmetric short signals in futures mode
- Report section shows `Short/Long` badge on futures datasets

#### New Strategies (14 total, up from 8)
| Strategy | Type |
|---|---|
| **Ichimoku Cloud** | Trend 🇯🇵 |
| **SuperTrend** | Trend (ATR-based) |
| **VWAP Deviation** | Mean-Reversion (crypto-native) |
| **CMF Trend** | Trend (Chaikin Money Flow) |
| **Hammer Pattern** | Candlestick 🕯️ |
| **Engulfing Pattern** | Candlestick 🕯️ |

#### ML/RL Fitness Scoring (Insights section)
- Scores each dataset 0–100 for ML suitability and RL suitability
- ML score: autocorrelation, Hurst exponent, IC, stationarity, sample size
- RL score: regime diversity, reward density, volatility clustering, fat tails, sample size
- Displays concrete bot recommendation: "use PPO on this pair" or "use GBM with these features"

#### Strategy Lab (new section)
- Select dataset + strategy from dropdowns
- Live parameter tuning with sliders (per-strategy parameter specs)
- Instant backtest with equity curve + position chart
- Position chart colored green (long) / red (short) / gray (flat) for futures
- **Grid Search Optimizer**: runs all parameter combinations in background, displays ranked results, auto-applies best params

#### Strategy Rotation on Price Chart (Insights section)
- Price line chart with colored background bands showing which strategy was best in each window
- Each background region's color = the strategy that had the highest Sharpe that period
- Legend shows all strategies used in rotation

#### Language Toggle (FA/EN)
- Globe-style toggle in topbar: FA / EN
- Switches all UI labels via `data-t` attribute system
- Switches HTML `dir` attribute (RTL ↔ LTR)

### Changed
- All strategy functions now accept `allow_short: bool = False` parameter
- `build_strategy_signals_with_params()` added for Lab custom param dispatch
- `STRATEGY_PARAM_GRIDS` and `STRATEGY_PARAM_SPECS` added to `rules.py` for Lab/Optimizer
- Insights API response now includes `price[]`, `allow_short`, and `ml_rl_fitness`
- Research API logs `[Short/Long]` flag when running on futures datasets
- `_build_recommendation` updated with new strategy-to-regime mapping (Ichimoku/SuperTrend/CMF = trend)
- Dashboard version updated to v1.1

### API Endpoints Added
| Endpoint | Method | Description |
|---|---|---|
| `/api/lab/params/{strategy}` | GET | Returns parameter spec for Lab UI |
| `/api/lab/run` | POST | Runs single strategy backtest with custom params |
| `/api/lab/optimize` | POST | Starts background Grid Search optimizer job |

## [1.0.0] — 2026-05-xx

Initial release with 8 strategies, download pipeline, research/report/insights sections.
