# Quant Research Platform

![Python](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)
![CCXT](https://img.shields.io/badge/CCXT-111%20exchanges-orange)
![Parquet](https://img.shields.io/badge/storage-Parquet-blueviolet)

**v1.2** — An end-to-end quantitative research platform covering data acquisition from **111+ exchanges**, interactive backtesting across **14 strategy families** (including Ichimoku, SuperTrend, and crypto-native strategies), full **long/short futures support**, an interactive **Strategy Lab** with grid-search optimizer, and **ML/RL fitness scoring** — all in a fully **bilingual (FA/EN)** browser dashboard with the **Midnight Aurora** theme.

```
┌─────────────────────────────────────────────────────────────────┐
│                  Quant Research Platform                        │
│                                                                 │
│  ┌────────────┐    ┌──────────────┐    ┌──────────────────────┐ │
│  │  CCXT      │    │   Nobitex    │    │  Binance Bulk        │ │
│  │ 111 exchgs │    │  UDF API     │    │  Monthly Archives    │ │
│  └─────┬──────┘    └──────┬───────┘    └──────────┬───────────┘ │
│        └──────────────────┴──────────────┬─────────┘           │
│                                          ▼                      │
│                          ┌───────────────────────────┐          │
│                          │   Parquet Data Store      │          │
│                          │   data/processed/*.parquet│          │
│                          └───────────────┬───────────┘          │
│                                          ▼                      │
│              ┌────────────────────────────────────────┐         │
│              │         FastAPI Web Dashboard          │         │
│              │  Download │ Inventory │ Research       │         │
│              │  Report   │ Insights  │ Lab  │ Logs    │         │
│              └────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Web Dashboard (primary interface)

| Section | Description |
|---|---|
| **Download** | Select any of 111+ CCXT exchanges or Nobitex, pick symbol, date range, multiple timeframes; real-time progress bar; saves to Parquet |
| **Data Inventory** | Visual grid of all downloaded datasets with exchange, symbol, timeframe, date range, row count, and file size |
| **Research** | Multi-select datasets and 14 strategies, configure capital/fees/slippage, run vectorized backtests (full Long+Short for futures) with live progress |
| **Report** | Interactive Plotly charts — equity curve with regime shading, drawdown panel, monthly heatmap, rolling Sharpe, sortable metrics table |
| **Insights** | Deep analysis: 90-day rolling strategy scores, regime detection, strategy rotation on price chart, ML/RL fitness scoring with bot hints |
| **Lab** | Customize strategy parameters with sliders, run instant backtests, and run Grid Search optimizer to find best params |
| **Edges** | Walk-forward out-of-sample survivors that live bots actually trade: live plan per symbol, per-timeframe edge distribution, timeframe-change alerts, scan history, and a one-click re-scan ([details](#walk-forward-edge-scan--live-bot-bridge)) |
| **Logs** | Live log viewer with level filtering |

**Language (FA/EN):** every string is fully translated via a single `web/i18n.js` dictionary — switching to English leaves no Persian behind, and the layout flips RTL↔LTR via CSS logical properties. The default language is chosen at install time (`make setup`) and stored in `configs/app.json`; a per-user choice in the top bar overrides it. The whole frontend is split into `dashboard.html` (shell) + `styles.css` + `i18n.js` + `app.js` and served as prefix-aware static assets, so it also works behind the `/admin/quant/` reverse proxy.

### Python Library

- **Data acquisition** — Binance monthly bulk archives with CCXT fallback; full Nobitex UDF history endpoint; incremental Parquet merge (never re-downloads existing data)
- **Validation** — gap detection, duplicate timestamps, outlier flagging, OHLCV consistency checks
- **Feature library** — 40+ technical and statistical features (trend, momentum, volatility, volume, market structure)
- **Factor research** — Information Coefficient, rank IC, conditional returns, factor decay, cross-factor correlation
- **Strategies** — 14 parameterised families: trend-following (EMA, MACD, Donchian, ATR, Ichimoku, SuperTrend, CMF), mean-reversion (RSI, Bollinger, Stochastic, VWAP), candlestick patterns (Hammer, Engulfing), and ML (GBM)
- **Backtesting engine** — vectorised long/flat/short with fees, slippage, execution delay; full futures short support (`allow_short=True`); Sharpe, Sortino, Calmar, CAGR, profit factor, win rate, max drawdown
- **ML/RL fitness scoring** — quantifies how suitable each dataset is for supervised ML vs reinforcement learning bots; provides actionable hints (Hurst exponent, IC, regime diversity, reward density)
- **Walk-forward & Monte Carlo** — out-of-sample validation and bootstrapped robustness analysis
- **ML research** — time-series-safe LightGBM/XGBoost return and volatility forecasting baselines

## Quick Start

### Install

```bash
git clone https://github.com/<your-org>/Quant_research
cd Quant_research
make setup          # installs deps and asks for the default dashboard language (EN/FA)
# or, non-interactive:
QR_DEFAULT_LANG=en ./scripts/setup.sh
# or just deps, keeping the FA default:
uv sync
```

`make setup` writes your language choice to `configs/app.json`. Re-pick it any time with `make lang`.

### Launch the web dashboard

```bash
make web
# or:
uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your browser.

### CLI (optional)

```bash
# Download Binance BTCUSDT 1h from 2020
uv run quant-research download --symbol BTCUSDT --timeframe 1h --start 2020-01-01

# Download all standard timeframes
uv run quant-research download-all --symbol BTCUSDT --timeframes 1m,5m,1h,1d --start 2020-01-01

# Download from Nobitex
uv run quant-research download-exchange --exchange nobitex --symbol BTCUSDT --timeframe 1h --start 2023-01-01

# Generate unified HTML research dashboard (static, all datasets × all strategies)
uv run quant-research research-all --data-dir data/processed --output reports/global_research/index.html

# Run backtest on a single dataset
uv run quant-research backtest data/processed/binance_BTCUSDT_1h.parquet --strategy ema_trend
```

## Supported Exchanges

### Via CCXT (111 exchanges)

All exchanges available in the [CCXT library](https://github.com/ccxt/ccxt) are supported, including Binance, Bybit, OKX, KuCoin, Gate.io, Bitfinex, Kraken, and more. The downloader uses paginated OHLCV fetching with rate-limit handling and automatic retries. For Binance specifically, the faster monthly bulk archive download path is used first, with CCXT as fallback.

### Nobitex (Iranian exchange)

Nobitex integration uses the public UDF history endpoint (`GET https://apiv2.nobitex.ir/market/udf/history`) with no authentication required. Supported timeframes: `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `3h`, `4h`, `1d`. Common symbols: `BTCUSDT`, `ETHUSDT`, `BTCIRT`, `ETHIRT`, and more.

## Strategies

All strategies support **long/flat** mode (spot) and **long/short** mode (futures, `-1/0/+1` signals).

### Trend-Following

| Strategy | Signal Logic | Futures Short Trigger |
|---|---|---|
| **EMA Trend** | Fast EMA > Slow EMA → Long | Fast EMA < Slow EMA → Short |
| **MACD Cross** | MACD line > Signal → Long | MACD line < Signal → Short |
| **Donchian Breakout** | Close > 55-bar high → Long | Close < 55-bar low → Short |
| **ATR Breakout** | Close > MA + 1.5×ATR → Long | Close < MA − 1.5×ATR → Short |
| **Ichimoku Cloud** 🇯🇵 | Above cloud + Tenkan > Kijun → Long | Below cloud + Tenkan < Kijun → Short |
| **SuperTrend** | Close above SuperTrend line → Long | Close below SuperTrend line → Short |
| **CMF Trend** | CMF > threshold → Long | CMF < −threshold → Short |

### Mean-Reversion

| Strategy | Long Entry | Short Entry |
|---|---|---|
| **RSI Mean Reversion** | RSI < 30 | RSI > 70 (futures) |
| **Bollinger Bands** | z-score < −2 | z-score > +2 (futures) |
| **Stochastic MR** | %D < 20 | %D > 80 (futures) |
| **VWAP Deviation** 🔷 | Price > 2% below VWAP | Price > 2% above VWAP |

### Candlestick Patterns (Japanese) 🕯️

| Strategy | Bullish Signal | Bearish Signal |
|---|---|---|
| **Hammer Pattern** | Hammer candle (long lower shadow) | Shooting Star (long upper shadow) |
| **Engulfing** | Bullish engulfing | Bearish engulfing |

### ML-Based

| Strategy | Method |
|---|---|
| **ML Signal (GBM)** | GradientBoosting on RSI/MACD/Bollinger/ATR features; trains on first 65% of bars |

## Backtesting Assumptions

| Parameter | Default | Notes |
|---|---|---|
| Initial capital | $10,000 | Configurable via UI |
| Transaction fee | 10 bps | One-way; charged on position changes |
| Slippage | 2 bps | One-way; charged on position changes |
| Execution delay | 1 bar | Signal at close, executed next bar |
| Spot position | 0–100% long | Binary long/flat |
| Futures position | −100% to +100% | Full long/short enabled automatically for futures datasets |

## Backtesting Assumptions

| Parameter | Default | Notes |
|---|---|---|
| Initial capital | $10,000 | Configurable via UI |
| Transaction fee | 10 bps | One-way; charged on position changes |
| Slippage | 2 bps | One-way; charged on position changes |
| Execution delay | 1 bar | Signal generated at bar close, executed at next open |
| Position sizing | 100% long / 0% cash | Binary long/flat, no leverage |

## Performance Metrics

The backtesting engine computes:

- **Total Return** — cumulative P&L over the period
- **CAGR** — compound annual growth rate
- **Sharpe Ratio** — annualised risk-adjusted return
- **Sortino Ratio** — downside-deviation-adjusted return
- **Calmar Ratio** — CAGR divided by maximum drawdown
- **Maximum Drawdown** — largest peak-to-trough equity decline
- **Profit Factor** — gross profits divided by gross losses
- **Win Rate** — fraction of bars with positive return

Both simple and logarithmic return series are available in the Research section.

## Report Dashboard

The Report section (accessible after running a backtest) provides:

**Equity Curve** — multi-strategy overlay with Buy & Hold benchmark; optional market regime shading (green bands = EMA20 > EMA50, red = EMA20 < EMA50); interactive hover with exact values.

**Drawdown Chart** — filled area chart per strategy showing depth and duration of drawdowns.

**Monthly Returns Heatmap** — calendar heatmap (year × month) with green/red colour scale, showing compounded monthly P&L. Available per strategy.

**Rolling Sharpe** — 30-bar rolling Sharpe ratio showing consistency over time and regime sensitivity.

**Metrics Table** — fully sortable table with colour coding (green = best in column, red = worst); one-click CSV export.

## Insights Engine

For each downloaded dataset, the Insights section analyses the **most recent 90 days** (or last 200 bars when 90-day data is sparse) and reports:

- **Market regime** — detected from EMA20/EMA50 cross and return autocorrelation: `trending_up`, `trending_down`, `ranging`, or `mean_reverting`
- **Strategy ranking** — all five strategies scored by Sharpe on the recent window
- **Best strategy recommendation** — highest Sharpe in the recent window
- **20-bar momentum** — percentage price change over the most recent 20 bars
- **Confidence bar chart** — relative score for each strategy

This is a statistical, rule-based system with no machine learning or LLM components. It is intended as a quick signal, not a trading recommendation.

## Walk-Forward Edge Scan → Live Bot Bridge

This is the part that turns research into a **deployable, automatically-refreshed edge**. The motivation: ML/RL trading bots tend to overfit — they look great in-sample and lose out-of-sample. This pipeline only promotes **rule strategies that stay positive across rolling out-of-sample windows**, with realistic futures costs (fees + slippage + **perpetual funding**) and short selling enabled, and then feeds those survivors to live freqtrade bots.

```
data/processed/*.parquet                    ← every downloaded exchange × symbol × timeframe
        │
        ▼  src/analysis/wf_scan.py
  walk-forward scan  (rolling train/test splits, no lookahead)
   • each strategy × direction × dataset
   • funding-aware backtest on every OOS test window
   • keep only: OOS mean > 0, ≥55% positive windows, Sharpe > 0
        │
        ├──►  outputs/wf_candidates.json   (manifest — the live bot reads this)
        └──►  outputs/wf_report.json       (dashboard report + alerts)  →  copied to soodo admin
        │
        ▼  scripts/refresh_candidates.py   (weekly cron)
  copy manifest → noches/user_data/wf_candidates.json
  reload Mickey  →  QuantResearchBridge picks best validated rule per pair
```

### What it scans

The scan runs over **every Parquet in `data/processed/` that has enough bars** (≥ one full train+test split). It is **exchange-agnostic and timeframe-agnostic** — it does not look at which exchange a live bot uses; instead it treats *consistency of an edge across independent venues* as the robustness signal. A representative run:

| Timeframe | Combos scanned | Edges passed |
|---|---|---|
| 15m | 44 | 0 |
| 1h | 66 | 1 |
| 4h | 176 | 32 |

→ robust edges concentrate on **4h** (e.g. BTC `donchian_breakout` consistent across 5 exchanges). 1d datasets are skipped automatically (too few bars for a valid split).

### Live bot (freqtrade) — `QuantResearchBridge`

`noches/user_data/strategies/QuantResearchBridge.py` is a freqtrade `IStrategy` that **reads the manifest and trades only validated rules** (pure-pandas, matching the research engine exactly). For each pair it picks the highest-Sharpe candidate **matching its live timeframe**; if a pair has no validated candidate, it stays flat. The live timeframe comes from the `QR_TIMEFRAME` env var (default `4h`).

### Automation & the timeframe policy

The full loop runs **daily** via one cron (`scripts/refresh_candidates.sh` at 23:00):

1. **Data refresh** (`scripts/refresh_data.py`) — incrementally appends fresh candles to every dataset in `data/processed` (dedup by timestamp; nothing is deleted) so edges are never computed on stale data.
2. **Re-scan** — rewrites the manifest + report, copies the manifest to the bots and the report to the soodo admin.
3. **Conditional reload** — Mickey is restarted **only when its live plan actually changes**, not on a fixed schedule. The script keeps a signature `{symbol: [strategy, allow_short]}` for the bot's pairs (`outputs/.live_plan_sig.json`); if today's scan yields the same plan, **no restart happens** (zero needless downtime); if the chosen rule/direction for a pair changes, it `docker restart`s and saves the new signature. So the restart cadence is driven by *how often the edge changes* — could be never, could be several days running — which is exactly "keep the bot in its best state automatically." (`--force-reload` overrides; `--mickey-pairs` sets which pairs count.)

**Switching the timeframe is deliberately *not* automatic.** If a stronger edge appears on a different timeframe, the scan emits a `better_timeframe` **alert** in `wf_report.json` (surfaced on both dashboards) rather than silently re-pointing a live, sold product. Changing the timeframe means restarting the container with a new `QR_TIMEFRAME` — a human-approved action, because it changes the character and risk profile of the bot.

### Edges dashboard

The **`/edges`** page (linked from the main dashboard sidebar) visualises the latest scan: live plan per symbol, per-timeframe edge distribution, top candidates, timeframe alerts, and scan history. It also exposes a **“run scan again”** button that triggers the same pipeline as a background job. A read-only mirror of the report is also rendered inside the **soodo admin** panel (`/admin/qr-edges`) so the business side can see what changed and when.

```bash
# run a scan manually (writes manifest + report, copies to bots, reloads Mickey)
.venv/bin/python scripts/refresh_candidates.py --reload-mickey

# scan only — write outputs but don't copy to bots or reload (for inspection)
.venv/bin/python scripts/refresh_candidates.py --noches "" --soodo-report ""
```

| Endpoint | Purpose |
|---|---|
| `GET /edges` | Edges dashboard page |
| `GET /api/edges` | Latest report + history + manifest summary |
| `POST /api/edges/refresh` | Trigger a fresh walk-forward scan (background job) |

## Repository Layout

```
Quant_research/
├── src/
│   ├── data/
│   │   ├── downloader.py      # Binance bulk + CCXT fallback pipeline
│   │   ├── nobitex.py         # Nobitex UDF OHLCV downloader
│   │   ├── storage.py         # Parquet read/write/merge
│   │   └── schema.py          # OHLCV column definitions and normalisation
│   ├── strategies/
│   │   └── rules.py           # EMA, RSI, Bollinger, Donchian, ATR strategies
│   ├── backtesting/
│   │   └── engine.py          # Vectorised backtester + metrics
│   ├── features/
│   │   └── library.py         # 40+ technical and statistical features
│   ├── factors/
│   │   └── research.py        # IC, rank IC, factor decay analysis
│   ├── analysis/
│   │   ├── global_report.py   # Multi-dataset HTML dashboard generator
│   │   ├── walk_forward.py    # Time-series cross-validation
│   │   ├── wf_scan.py         # Walk-forward edge scan + manifest/report/alerts
│   │   ├── monte_carlo.py     # Bootstrap robustness analysis
│   │   ├── regime.py          # Market regime detection
│   │   └── portfolio.py       # Cross-asset aggregation
│   ├── ml/
│   │   └── research.py        # LightGBM/XGBoost return + volatility forecasting
│   ├── validation/
│   │   └── quality.py         # Data quality checks and gap detection
│   ├── web/
│   │   ├── app.py             # FastAPI server (all API endpoints)
│   │   └── jobs.py            # Background job manager (download, research)
│   ├── cli/
│   │   └── app.py             # Typer CLI entrypoint
│   └── config.py              # Pydantic project configuration models
├── web/
│   ├── dashboard.html         # Single-page browser dashboard
│   └── edges.html             # Walk-forward edges dashboard (/edges)
├── scripts/
│   ├── refresh_candidates.py  # Re-scan, write manifest+report, copy to bots, reload
│   └── refresh_candidates.sh  # Weekly cron wrapper (host)
├── data/
│   ├── processed/             # OHLCV Parquet files ({exchange}_{symbol}_{tf}.parquet)
│   └── research/              # Feature matrices and research artefacts
├── docs/                      # Methodology documentation
├── reports/                   # Generated HTML and Markdown reports
├── tests/                     # Pytest suite
├── notebooks/                 # Exploratory notebooks
├── configs/
│   └── research.yaml          # Research pipeline configuration
├── pyproject.toml
└── Makefile
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
make test

# Lint
make lint

# Type-check
make typecheck

# All quality gates
make quality

# Start web dashboard (with auto-reload)
make web
```

## Data Storage

All data is stored in `data/processed/` as Parquet files. The naming convention is:

```
{exchange}_{symbol}_{timeframe}.parquet
```

Examples: `binance_BTCUSDT_1h.parquet`, `nobitex_BTCUSDT_1d.parquet`, `bybit_ETHUSDT_4h.parquet`

Downloads are **incremental**: re-running a download for an existing file only fetches new candles and merges them, never duplicating existing data.

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | Web server and API |
| `ccxt` | 111+ exchange connectors |
| `pandas` + `pyarrow` | Data manipulation and Parquet I/O |
| `numpy` + `scipy` | Numerical computation |
| `plotly` | Interactive charts in the dashboard |
| `scikit-learn` + `lightgbm` + `xgboost` | ML baselines |
| `ta` | Technical indicator helpers |
| `pydantic` | Configuration models |
| `typer` + `rich` | CLI interface |

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | System design and module responsibilities |
| [Data Pipeline](docs/data_pipeline.md) | Acquisition, normalisation, and storage |
| [Strategy Research](docs/strategy_research.md) | Strategy definitions and signal logic |
| [Backtesting](docs/backtesting.md) | Engine assumptions and metrics |
| [Factor Research](docs/factor_research.md) | Alpha signal research methodology |
| [Feature Engineering](docs/feature_engineering.md) | Technical feature library |
| [Walk-Forward](docs/walk_forward.md) | Out-of-sample validation |
| [ML Research](docs/ml_research.md) | Machine learning baselines |
| [Monte Carlo](docs/monte_carlo.md) | Bootstrap robustness |
| [Portfolio Research](docs/portfolio_research.md) | Multi-asset aggregation |

## Disclaimer

This repository is research infrastructure. It is not financial advice and does not represent live trading performance. All strategy results are in-sample unless explicitly labelled as walk-forward out-of-sample results. Past backtest performance does not predict future returns.
