"""Guards the FA/EN contract of the dashboard.

Selecting EN must produce a UI with *no* Persian anywhere. Three things can
break that, and each is checked here:

  1. a key defined in the `fa` dict but missing from `en` — `t()` falls back to
     Persian rather than showing the raw key, so the leak is silent;
  2. a Persian string literal in the markup or the app logic that never passes
     through `t()`, or markup carrying Persian text with no `data-i18n` tag;
  3. a backend job message whose fallback text is Persian — it surfaces
     whenever the paired `message_code` is missing from the dictionaries.

The dictionaries are parsed with a regex rather than a JS engine: the file is a
plain object literal of `key: 'value'` pairs, and requiring node here would make
the suite unrunnable in the CI image.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PERSIAN = re.compile(r"[؀-ۿ]")

# Codes the backend can emit for a given field, so the dictionaries can be
# checked against what actually reaches the browser rather than a guess.
PIPELINE_STAGES = ("init", "data_refresh", "wf_scan", "pair_rotation", "qr_bridge_refresh")
FLEET_ALERT_CODES = ("gross_leverage", "net_delta", "asset_concentration",
                     "bot_leverage", "bot_db_missing", "crowding_corr")
STRESS_VERDICTS = ("ok", "hit", "critical", "wiped")
HEARTBEAT_STATUSES = ("ok", "late", "missing")
ALTDATA_HINTS = ("dvol_high", "dvol_low", "crowd_long", "crowd_short", "backwardation")
ML_VERDICTS = ("predictable", "weak", "noise")
SECTIONS = ("download", "inventory", "research", "report", "insights", "lab", "edges",
            "crossex", "fleet", "altdata", "attribution", "trials", "stress",
            "capacity", "portfolio", "models", "pipeline", "quality", "logs")


def _dicts() -> tuple[dict[str, str], dict[str, str]]:
    """Split i18n.js into its `fa:` and `en:` halves and pull out the keys."""
    src = (WEB / "i18n.js").read_text(encoding="utf-8")
    body = src[src.index("const I18N = {"):src.index("const STRATEGY_LABELS")]
    fa_at, en_at = body.index("\n  fa: {"), body.index("\n  en: {")
    assert fa_at < en_at, "expected the fa dict before the en dict"
    # Several keys share a line (`title_x: '…', sub_x: '…'`), so match anywhere
    # rather than anchoring to the indent. Values are single-quoted with
    # backslash escapes, which the alternation below consumes.
    pair = re.compile(r"\b([a-z0-9_]+):\s*'((?:[^'\\]|\\.)*)'")
    fa = {m.group(1): m.group(2) for m in pair.finditer(body[fa_at:en_at])}
    en = {m.group(1): m.group(2) for m in pair.finditer(body[en_at:])}
    assert len(fa) > 600 and len(en) > 600, f"parser found too few keys: {len(fa)}/{len(en)}"
    return fa, en


def test_every_fa_key_has_an_en_translation():
    fa, en = _dicts()
    missing = sorted(set(fa) - set(en))
    assert not missing, f"keys fall back to Persian in EN mode: {missing}"


def test_no_persian_in_the_en_dictionary():
    _, en = _dicts()
    leaks = sorted(k for k, v in en.items() if PERSIAN.search(v))
    assert not leaks, f"Persian text inside EN translations: {leaks}"


@pytest.mark.parametrize("prefix,codes", [
    ("epb_stage_", PIPELINE_STAGES),
    ("fleet_alert_", FLEET_ALERT_CODES),
    ("stress_v_", STRESS_VERDICTS),
    ("pipe_s_", HEARTBEAT_STATUSES),
    ("alt_hint_", ALTDATA_HINTS),
    ("verdict_", ML_VERDICTS),
    ("title_", SECTIONS),
    ("sub_", SECTIONS),
])
def test_backend_codes_all_resolve(prefix, codes):
    """The dashboard builds these keys as `prefix + code`. An unlisted code
    renders the raw key, so both dicts must cover every value the backend emits."""
    fa, en = _dicts()
    for code in codes:
        key = prefix + code
        assert key in fa and key in en, f"{key} is not translated"


def test_no_persian_string_literals_in_app_js():
    """Every user-facing string in app.js must go through t()."""
    lines = (WEB / "app.js").read_text(encoding="utf-8").splitlines()
    bad = [f"{n}: {ln.strip()[:100]}" for n, ln in enumerate(lines, 1) if PERSIAN.search(ln)]
    assert not bad, "hardcoded Persian in app.js:\n" + "\n".join(bad)


def test_markup_persian_is_always_tagged_for_translation():
    """Persian in dashboard.html is fine as the default rendering, but only
    inside an element applyI18n() will overwrite."""
    from html.parser import HTMLParser

    void = {"br", "img", "input", "hr", "meta", "link", "source"}

    class Scan(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.stack: list[bool] = []
            self.bad: list[str] = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            for k, v in a.items():
                if v and PERSIAN.search(v) and k in ("placeholder", "title", "alt", "aria-label"):
                    paired = "data-i18n-" + ("ph" if k == "placeholder" else k)
                    if paired not in a:
                        self.bad.append(f"line {self.getpos()[0]}: untranslated @{k}")
            if tag not in void:
                covered = any(k.startswith("data-i18n") for k in a)
                self.stack.append(covered or bool(self.stack and self.stack[-1]))

        def handle_endtag(self, tag):
            if tag not in void and self.stack:
                self.stack.pop()

        def handle_data(self, data):
            text = data.strip()
            if text and PERSIAN.search(text) and not (self.stack and self.stack[-1]):
                self.bad.append(f"line {self.getpos()[0]}: untagged text {text[:60]!r}")

    scan = Scan()
    scan.feed((WEB / "dashboard.html").read_text(encoding="utf-8"))
    assert not scan.bad, "Persian that survives a switch to EN:\n" + "\n".join(scan.bad)


def test_backend_job_messages_are_language_neutral():
    """Job/alert fallback text is shown verbatim when a consumer ignores
    message_code, so it must not be Persian. Comments and docstrings are
    exempt — only string literals that can reach the browser matter."""
    import ast

    for rel in ("src/web/app.py", "src/analysis/wf_scan.py"):
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        leaks = [
            node.value[:70]
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node not in docstrings and PERSIAN.search(node.value)
        ]
        assert not leaks, f"Persian string literals in {rel}: {leaks}"
