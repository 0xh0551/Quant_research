# Changelog

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
