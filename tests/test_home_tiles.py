"""Guards the home screen's contract, which is easy to lose one tile at a time.

The launcher exists to say nineteen different things at a glance. Two failures
make it useless and neither shows up as an error:

  1. two tiles drawing the same chart form — the wall stops being scannable and
     becomes a wall of identical bar charts;
  2. two tiles plotting the same field — the same series repeated teaches
     nothing, and it happened: inventory, research and lab all charted the
     store's timeframe mix at once.

Parsed with regex rather than a JS engine: the renderers are a plain object
literal of `name(d) { ... }` methods, and requiring node here would make the
suite unrunnable in the CI image — the same trade the i18n guard makes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_JS = (ROOT / "web" / "home.js").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "web" / "dashboard.html").read_text(encoding="utf-8")

# Each chart helper renders one visual form; the tile bodies pick exactly one.
CHART_FNS = ("cGrid", "cStack", "cRing", "cSpan", "cBullets", "cChips", "cDecay",
             "cFunnel", "cLollipop", "cLogStrip", "cDumbbell", "cArc", "cTreemap",
             "cLossAxis", "cWaterfall", "cArea", "cBudgetPips", "cSlots", "cHours")


def _renderers() -> dict[str, str]:
    """Split HOME_RENDER into `{tile: body source}`."""
    block = HOME_JS[HOME_JS.index("const HOME_RENDER = {"):HOME_JS.index("\n// ═", HOME_JS.index("const HOME_RENDER = {"))]
    out: dict[str, str] = {}
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([a-z]+)\(d\) \{", block, re.M)]
    for i, (name, at) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(block)
        out[name] = block[at:end]
    return out


def test_every_section_has_a_renderer():
    sections = set(re.findall(r'id="sec-([a-z]+)"', DASHBOARD)) - {"home"}
    assert set(_renderers()) == sections


def test_no_two_tiles_use_the_same_chart_form():
    """A wall of nineteen identical bar charts is not a dashboard."""
    used: dict[str, list[str]] = {}
    for tile, src in _renderers().items():
        forms = [fn for fn in CHART_FNS if re.search(rf"\b{fn}\(", src)]
        assert len(forms) == 1, f"{tile} draws {forms or 'no chart'}, expected exactly one"
        used.setdefault(forms[0], []).append(tile)
    repeats = {f: t for f, t in used.items() if len(t) > 1}
    assert not repeats, f"chart forms used more than once: {repeats}"
    assert len(used) == len(_renderers())


def test_no_two_tiles_serve_the_same_series():
    """Every tile must chart data belonging to *its* module.

    The parquet sweep is the one source several tiles share, and it is exactly
    where this went wrong: inventory, research and lab each charted its
    `by_timeframe` mix, so three panels drew an identical bar chart. Scalars off
    the sweep are fine on several tiles — a count is context, not a chart — but
    a *series* it derives may back at most one tile's graphic.
    """
    home_py = (ROOT / "src" / "web" / "home.py").read_text(encoding="utf-8")
    body = home_py[home_py.index("# \u2500\u2500 per-tile builders"):home_py.index("_BUILDERS = {")]
    builders = re.split(r"^def _tile_", body, flags=re.M)[1:]

    owners: dict[str, list[str]] = {}
    for b in builders:
        name = b.split("(")[0]
        for key in ("by_timeframe", "by_exchange", "recency", "matrix", "by_symbol"):
            if re.search(r's\["' + key + r'"\]', b):
                owners.setdefault(key, []).append(name)
    shared = {k: v for k, v in owners.items() if len(v) > 1}
    assert not shared, f"a shared series backs more than one tile's chart: {shared}"


@pytest.mark.parametrize("tile", sorted(_renderers()))
def test_tile_shows_two_or_three_numbers(tile):
    """More than three headline numbers stops being readable at the row height
    a nineteen-tile screenful allows."""
    n = len(re.findall(r"\{ l: t\(", _renderers()[tile]))
    assert 2 <= n <= 3, f"{tile} shows {n} KPIs"


def test_renderers_do_not_reach_into_app_js_globals():
    """home.js loads before app.js and sibling classic scripts share one global
    lexical scope, so borrowing a `const` from app.js is a load-order bug that
    only shows at runtime. It has bitten twice: `esc`, then STRATEGY_TAG_COLORS."""
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    top = r"^(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)"
    any_decl = r"\b(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)"
    app_globals = set(re.findall(top, app_js, re.M))
    home_globals = set(re.findall(top, HOME_JS, re.M))

    # comments name app.js symbols on purpose; only real reads count
    code = re.sub(r"/\*.*?\*/", " ", HOME_JS, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    home_declared = set(re.findall(any_decl, code)) | {"showSection"}   # called at click time
    borrowed = sorted(g for g in app_globals - home_declared
                      if re.search(r"(?<![\w$.])" + re.escape(g) + r"(?![\w$])", code))
    assert not borrowed, f"home.js reads app.js globals: {borrowed}"
    assert not (app_globals & home_globals), \
        f"redeclared in both scripts: {sorted(app_globals & home_globals)}"
