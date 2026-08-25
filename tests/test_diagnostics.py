"""The diagnostics report, and the one thing it must never do.

Every problem this app has had reported to it arrived as a photograph of a
screen. A paste-able report fixes that -- but a report that carries the OBS
password or the dashboard token into a chat window is worse than no report at
all, and the first version did exactly that: not from config.yaml, which was
redacted properly, but from the LOG, where the startup banner prints the
dashboard URL with the token in its query string.

So it is scrubbed twice: by key for config, and by value over the whole text.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg, webui                                  # noqa: E402


def report() -> str:
    app = webui.Server.__new__(webui.Server)
    app.engine = None
    return app.diagnostics()["text"]


def test_it_says_what_it_is_running():
    text = report()
    for want in ("AutoStream", "Python", "OS", "Home"):
        assert want in text


def test_it_reports_obs_and_ffmpeg():
    text = report()
    assert "OBS" in text
    assert "ffmpeg" in text


def test_no_secret_value_survives_anywhere():
    """The whole point. Checked against the real config, prose included."""
    text = report()
    c = cfg.load()
    for value in (c.obs.password, c.rules.web_token,
                  c.youtube.stream_id, c.youtube.ingestion_address):
        if value and len(str(value)) >= 6:
            assert str(value) not in text, "a secret value reached the report"


def test_a_token_bearing_url_is_redacted_but_still_legible():
    """The log's startup banner is the exact line that leaked. The shape is
    kept because "the UI had a URL" is itself worth seeing."""
    app = webui.Server.__new__(webui.Server)
    app.engine = None
    got = app._scrub("AutoStream UI: http://192.168.0.4:8787/?k=SuperSecret123",
                     cfg.load())
    assert "SuperSecret123" not in got
    assert "?k=(removed)" in got


def test_a_short_value_is_not_scrubbed_out_of_ordinary_words():
    """Scrubbing a two-character secret would redact half the English in the
    log, so only values long enough to be secrets are removed."""
    app = webui.Server.__new__(webui.Server)
    app.engine = None
    raw = cfg.load_raw()
    raw.setdefault("obs", {})["password"] = "ab"
    got = app._scrub("a cabbage and an absolute path", cfg.Config(raw))
    assert "cabbage" in got
