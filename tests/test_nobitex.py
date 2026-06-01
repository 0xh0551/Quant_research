from __future__ import annotations

from src.data.nobitex import NobitexOHLCVDownloader, nobitex_resolution


def test_nobitex_resolution_mapping():
    assert nobitex_resolution("1m") == "1"
    assert nobitex_resolution("5m") == "5"
    assert nobitex_resolution("1h") == "60"
    assert nobitex_resolution("1d") == "D"


def test_nobitex_payload_parser():
    payload = {
        "s": "ok",
        "t": [1_704_067_200, 1_704_153_600],
        "o": [100.0, 101.0],
        "h": [105.0, 106.0],
        "l": [95.0, 96.0],
        "c": [101.0, 102.0],
        "v": [10.5, 11.5],
    }
    frame = NobitexOHLCVDownloader()._parse_payload(payload)
    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert frame["timestamp"].dt.tz is not None
