from __future__ import annotations

from src.portfolio import fleet_risk


def test_check_limits_flags_breaches():
    fleet = {
        "gross_leverage": 4.0,          # limit 3.0 → warn (below 1.5x limit)
        "net_beta_delta_pct": -450.0,   # limit 200 → critical (>1.5x)
        "gross_notional": 1000.0,
        "avg_pairwise_corr": 0.9,       # limit 0.75 → warn
    }
    per_asset = [
        {"base": "BTC", "gross_notional": 700.0},   # 70% > 60% → warn
        {"base": "ETH", "gross_notional": 300.0},
    ]
    per_bot = [
        {"bot": "A", "gross_leverage": 9.0, "db_found": True},   # > 8 → warn
        {"bot": "B", "gross_leverage": 1.0, "db_found": False},  # missing → critical
    ]
    alerts = fleet_risk._check_limits(fleet, per_asset, per_bot, dict(fleet_risk.DEFAULT_LIMITS))
    codes = {a["code"] for a in alerts}
    assert codes == {
        "gross_leverage", "net_delta", "asset_concentration",
        "bot_leverage", "bot_db_missing", "crowding_corr",
    }
    by_code = {a["code"]: a for a in alerts}
    assert by_code["net_delta"]["level"] == "critical"
    assert by_code["bot_db_missing"]["level"] == "critical"
    assert by_code["gross_leverage"]["level"] == "warn"
    assert by_code["asset_concentration"]["context"] == "BTC"


def test_check_limits_quiet_inside_envelope():
    fleet = {
        "gross_leverage": 1.0, "net_beta_delta_pct": 50.0,
        "gross_notional": 1000.0, "avg_pairwise_corr": 0.3,
    }
    per_asset = [{"base": "BTC", "gross_notional": 400.0}]
    per_bot = [{"bot": "A", "gross_leverage": 2.0, "db_found": True}]
    assert fleet_risk._check_limits(fleet, per_asset, per_bot, dict(fleet_risk.DEFAULT_LIMITS)) == []


def test_build_snapshot_degrades_without_config(tmp_path, monkeypatch):
    # point the local config at a nonexistent file → empty fleet, no crash
    monkeypatch.setenv("QR_LOCAL_CONFIG", str(tmp_path / "nope.json"))
    fleet_risk.local_config._load.cache_clear()
    try:
        snap = fleet_risk.build_snapshot()
        assert snap["positions"] == []
        assert snap["fleet"]["n_positions"] == 0
        assert snap["alerts"] == []
    finally:
        fleet_risk.local_config._load.cache_clear()
