"""The home screen's single data call.

Nineteen widgets load from one payload, so this endpoint has two obligations
that are easy to lose: it must stay *cheap* (artifacts already on disk plus a
stat sweep — never a backtest or an exchange call), and it must never fail as a
whole. A missing or corrupt artifact should blank one tile, not the launcher.
"""

from __future__ import annotations

import json

import pytest
from src.web import home


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Point the module at empty directories and clear both of its caches."""
    outputs = tmp_path / "outputs"
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    for d in (outputs, data, logs):
        d.mkdir()
    monkeypatch.setattr(home, "OUTPUTS_DIR", outputs)
    monkeypatch.setattr(home, "DATA_DIR", data)
    monkeypatch.setattr(home, "LOG_DIR", logs)
    home._cache.update(at=0.0, payload=None)
    home._ds_cache.update(at=0.0, value=None)
    yield outputs, data
    home._cache.update(at=0.0, payload=None)
    home._ds_cache.update(at=0.0, value=None)


TILES = ("download", "inventory", "research", "report", "insights", "lab", "edges",
         "crossex", "fleet", "altdata", "attribution", "trials", "stress",
         "capacity", "portfolio", "models", "pipeline", "quality", "logs")


def test_every_tile_is_present_on_a_bare_install(isolated):
    """A fresh checkout has no outputs/ artifacts at all; the grid still builds."""
    payload = home.summary(force=True)
    assert set(payload["tiles"]) == set(TILES)
    assert payload["generated_at"]
    for key, tile in payload["tiles"].items():
        assert isinstance(tile, dict), key
        assert not tile.get("error"), f"{key} raised on empty artifacts"


def test_corrupt_artifact_blanks_one_tile_not_the_grid(isolated):
    outputs, _ = isolated
    (outputs / "fleet_risk.json").write_text("{not json at all", encoding="utf-8")
    payload = home.summary(force=True)
    assert set(payload["tiles"]) == set(TILES)
    assert payload["tiles"]["edges"] is not None       # unrelated tile unaffected
    assert payload["tiles"]["fleet"]["equity_usd"] is None


def test_reads_the_artifacts_it_advertises(isolated):
    outputs, _ = isolated
    (outputs / "fleet_risk.json").write_text(json.dumps({
        "generated_at": "2026-08-20T00:00:00+00:00",
        "fleet": {"equity_usd": 7000.0, "gross_leverage": 0.5, "n_positions": 3, "n_bots": 2},
        "per_bot": [{"bot": "bot1", "gross_leverage": 0.4, "n_open": 2, "realized_pnl": -5.0}],
        "per_asset": [{"base": "BTC", "gross_notional": 100.0, "bots": ["bot1"]},
                      {"base": "ETH", "gross_notional": 300.0, "bots": ["bot1"]}],
        "limits": {"max_gross_leverage": 3.0},
        "alerts": [{"code": "gross_leverage"}],
    }), encoding="utf-8")
    (outputs / "wf_report.json").write_text(json.dumps({
        "n_scanned": 100, "n_passed": 10, "n_robust": 4, "n_deployable": 2,
        "top": [{"symbol": "BTCUSDT", "strategy": "ema_trend", "timeframe": "1h",
                 "oos_sharpe": 2.5, "deployable": True}],
        "alerts": [], "rigor": {"median_pbo": 0.2},
        "generated_at": "2026-08-20T00:00:00+00:00",
    }), encoding="utf-8")

    tiles = home.summary(force=True)["tiles"]
    assert tiles["fleet"]["equity_usd"] == 7000.0
    assert tiles["fleet"]["n_alerts"] == 1
    # the edges tile charts the survival funnel, in order
    assert [f["k"] for f in tiles["edges"]["funnel"]] == [
        "scanned", "passed", "robust", "deployable"]
    assert [f["v"] for f in tiles["edges"]["funnel"]] == [100, 10, 4, 2]
    # portfolio shares fleet's per_asset and must normalise to percentages
    assert [a["pct"] for a in tiles["portfolio"]["top"]] == [75.0, 25.0]


def test_dataset_sweep_never_opens_a_parquet(isolated, monkeypatch):
    """The store is ~1 GB; the tile KPIs come from the filename and stat block."""
    _, data = isolated
    for name in ("bybit_futures_BTCUSDT_1h", "bybit_futures_BTCUSDT_15m",
                 "okx_ETHUSDT_1h", "gate_futures_ETHUSDT_1h"):
        (data / f"{name}.parquet").write_bytes(b"not-a-real-parquet")

    import pandas as pd

    def explode(*a, **k):  # pragma: no cover - only runs if the sweep regresses
        raise AssertionError("home summary must not parse parquet files")

    monkeypatch.setattr(pd, "read_parquet", explode)

    tiles = home.summary(force=True)["tiles"]
    inv = tiles["inventory"]
    assert inv["n_datasets"] == 4
    assert inv["n_symbols"] == 2                    # BTCUSDT + ETHUSDT
    # the coverage grid is venue x timeframe, spot and futures folded together
    m = inv["matrix"]
    assert m["timeframes"] == ["15m", "1h"]
    cells = {v: dict(zip(m["timeframes"], row, strict=True))
             for v, row in zip(m["venues"], m["cells"], strict=True)}
    assert cells["bybit"] == {"15m": 1, "1h": 1}
    assert cells["okx"] == {"15m": 0, "1h": 1}
    # ETHUSDT lives on okx and gate, BTCUSDT only on bybit
    assert tiles["crossex"]["multi_venue_symbols"] == 1
    assert tiles["download"]["n_datasets"] == 4


def test_payload_carries_only_what_the_tiles_read(isolated):
    """Each tile shows three numbers and one chart. The endpoint emits exactly
    the fields that view consumes — a field nothing reads is dead weight on
    every poll, and it drifts out of sync unnoticed."""
    fields = {k: set(v) for k, v in home.summary(force=True)["tiles"].items()}
    expected = {
        "inventory": {"n_datasets", "n_symbols", "total_gb", "matrix"},
        "download": {"recency", "n_venues", "newest_age_h", "n_datasets"},
        "quality": {"scannable_pct", "n_scannable", "n_datasets", "median_bars", "stale_gt_3d"},
        "research": {"n_runs", "n_symbols", "first", "last",
                     "median_span_days", "max_span_days"},
        "insights": {"gauges", "dvol_btc", "ls_ratio_btc", "n_event_symbols"},
        "lab": {"strategies", "n_strategies", "n_params"},
        "report": {"sharpes", "n_top", "best_sharpe", "best_return", "age_h"},
        "edges": {"funnel", "median_pbo", "live_timeframe", "age_h"},
        "trials": {"age_h", "n_deflated_pass", "n_unique", "pass_rate", "strategies"},
        "capacity": {"points", "median_capacity", "min_capacity", "n_books", "age_h"},
        "crossex": {"carry", "best_spread", "multi_venue_symbols", "n_venues", "carry_age_h"},
        "fleet": {"gross_leverage", "max_gross_leverage", "equity_usd",
                  "net_beta_delta_pct", "n_positions", "n_alerts", "age_h"},
        "portfolio": {"top", "gross_usd", "hhi", "n_assets", "age_h"},
        "stress": {"ticks", "worst_pct", "worst_key", "n_liquidations",
                   "n_scenarios", "age_h"},
        "attribution": {"steps", "net", "window_days", "age_h"},
        "altdata": {"dvol_series", "dvol_btc", "dvol_eth", "liquidations_24h_usd", "age_h"},
        "pipeline": {"jobs", "ok", "late", "missing", "n_jobs", "healthy",
                     "run_state", "run_step", "age_h"},
        "models": {"split", "n_pairs", "n_bots", "n_dropped", "age_h"},
        "logs": {"hourly", "n_hours", "n_errors", "n_warnings", "n_lines"},
    }
    assert fields == expected


def test_result_is_ttl_cached(isolated):
    first = home.summary(force=True)
    assert home.summary() is first                  # inside the TTL, same object
    assert home.summary(force=True) is not first


def test_demo_payload_matches_the_live_shape(isolated):
    """A screenshot taken in demo mode has to show the real interface.

    The moment the fixture's shape drifts from the endpoint's, the published
    screenshots stop being evidence of anything — tiles would render from
    fields the live payload no longer has, or miss ones it gained.
    """
    from src.web import demo

    live = home.summary(force=True)["tiles"]
    fake = demo.summary()["tiles"]
    assert set(fake) == set(live)
    for tile in sorted(live):
        assert set(fake[tile]) == set(live[tile]), f"{tile} drifted"


def test_demo_is_off_unless_asked_for(monkeypatch):
    from src.web import demo

    monkeypatch.delenv("QR_DEMO", raising=False)
    assert not demo.enabled()
    monkeypatch.setenv("QR_DEMO", "1")
    assert demo.enabled()
    monkeypatch.setenv("QR_DEMO", "0")
    assert not demo.enabled()
