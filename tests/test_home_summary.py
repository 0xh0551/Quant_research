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
        "per_bot": [{"bot": "Popeye", "gross_leverage": 0.4, "n_open": 2, "realized_pnl": -5.0}],
        "per_asset": [{"base": "BTC", "gross_notional": 100.0, "bots": ["Popeye"]},
                      {"base": "ETH", "gross_notional": 300.0, "bots": ["Popeye"]}],
        "limits": {"max_gross_leverage": 3.0},
        "alerts": [{"code": "gross_leverage"}],
    }), encoding="utf-8")
    (outputs / "wf_report.json").write_text(json.dumps({
        "n_scanned": 100, "n_passed": 10, "n_robust": 4, "n_deployable": 2,
        "by_timeframe": {"1h": {"scanned": 60, "passed": 7, "robust": 3},
                         "15m": {"scanned": 40, "passed": 3, "robust": 1}},
        "top": [{"symbol": "BTCUSDT", "strategy": "ema_trend", "timeframe": "1h",
                 "oos_sharpe": 2.5, "deployable": True}],
        "alerts": [], "rigor": {"median_pbo": 0.2},
        "generated_at": "2026-08-20T00:00:00+00:00",
    }), encoding="utf-8")

    tiles = home.summary(force=True)["tiles"]
    assert tiles["fleet"]["equity_usd"] == 7000.0
    assert tiles["fleet"]["n_alerts"] == 1
    # by_timeframe carries `passed`, not a bare count — a wrong key reads as zero
    assert {b["k"]: b["v"] for b in tiles["edges"]["by_timeframe"]} == {"15m": 3, "1h": 7}
    assert {b["k"]: b["v"] for b in tiles["edges"]["by_timeframe_robust"]} == {"15m": 1, "1h": 3}
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
    assert {b["k"]: b["v"] for b in inv["by_timeframe"]} == {"15m": 1, "1h": 3}
    assert {b["k"]: b["v"] for b in tiles["download"]["by_exchange"]} == {
        "bybit": 2, "okx": 1, "gate": 1}
    # ETHUSDT lives on okx and gate_futures, BTCUSDT only on bybit_futures
    assert tiles["crossex"]["multi_venue_symbols"] == 1


def test_payload_carries_only_what_the_tiles_read(isolated):
    """Each tile shows three numbers and one chart. The endpoint emits exactly
    the fields that view consumes — a field nothing reads is dead weight on
    every poll, and it drifts out of sync unnoticed."""
    fields = {k: set(v) for k, v in home.summary(force=True)["tiles"].items()}
    expected = {
        "inventory": {"n_datasets", "n_symbols", "total_gb", "by_timeframe", "newest_age_h"},
        "download": {"refreshed_24h", "refreshed_7d", "n_venues", "by_exchange", "newest_age_h"},
        "quality": {"scannable_pct", "median_bars", "stale_gt_3d", "bars_hist"},
        "research": {"n_runs", "n_datasets", "n_symbols", "by_timeframe"},
        "insights": {"event_risk", "dvol_btc", "ls_ratio_btc", "top_strategies"},
        "lab": {"n_strategies", "n_params", "n_datasets", "by_timeframe"},
        "report": {"n_top", "best", "sharpes", "age_h"},
        "edges": {"n_passed", "n_deployable", "median_pbo", "live_timeframe",
                  "by_timeframe", "by_timeframe_robust", "age_h"},
        "trials": {"n_deflated_pass", "age_h", "n_unique", "pass_rate", "strategies"},
        "capacity": {"n_books", "median_capacity", "total_capacity", "rows", "age_h"},
        "crossex": {"best_spread", "multi_venue_symbols", "n_venues", "carry", "carry_age_h"},
        "fleet": {"equity_usd", "gross_leverage", "max_gross_leverage",
                  "net_beta_delta_pct", "n_alerts", "bots", "age_h"},
        "portfolio": {"gross_usd", "hhi", "n_assets", "top", "age_h"},
        "stress": {"worst", "rows", "n_liquidations", "age_h"},
        "attribution": {"net", "intended", "fees", "funding", "exit_slip",
                        "mfe_capture_avg", "age_h"},
        "altdata": {"dvol_btc", "dvol_eth", "dvol_series", "liquidations_24h_usd", "age_h"},
        "pipeline": {"healthy", "n_jobs", "ok", "late", "missing",
                     "run_state", "run_step", "age_h"},
        "models": {"n_pairs", "n_bots", "n_dropped", "bots", "age_h"},
        "logs": {"n_lines", "n_errors", "n_warnings", "levels"},
    }
    assert fields == expected


def test_result_is_ttl_cached(isolated):
    first = home.summary(force=True)
    assert home.summary() is first                  # inside the TTL, same object
    assert home.summary(force=True) is not first
