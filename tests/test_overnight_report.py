"""Findings from the overnight test report of 2026-09-25, each pinned.

The report drove every page with Playwright against a sandboxed copy of the
app, fuzzed the API, and injected faults (OBS killed, the recording killed,
uploads failing). Most of what it found lives in one of the flow suites
already -- tests/verify/test_engine_flows.py for the state machine,
test_upload.py and test_forget_and_report.py for those two. These are the
rest: the ones that are a line of script, a setting's validation, or a
string that must never appear again.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                   # noqa: E402

from autostream import engine as engine_mod, schema, webui      # noqa: E402
from autostream.state import IDLE, LIVE                         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _ui(name: str) -> str:
    mod = importlib.import_module(f"autostream.ui.{name}")
    return "\n".join(getattr(mod, n) for n in dir(mod)
                     if n.isupper() and isinstance(getattr(mod, n), str))


# ------------------------------------------------------ the watermark (#27)

def test_nobody_elses_channel_is_written_on_a_clip():
    """Every stranger's Shorts carried "@YuvaNeta" and the developer's logo:
    a literal fallback, with the user's own channel settings never read."""
    for f in (ROOT / "autostream" / "clips").glob("*.py"):
        if f.name == "studio_refs.py":
            continue                        # measurements of other channels
        text = f.read_text(encoding="utf-8")
        assert "@YuvaNeta" not in text, f.name
        assert "yuvaneta-light" not in text, f.name


def test_the_watermark_is_the_users_own_channel(monkeypatch, tmp_path):
    from autostream import cfg
    from autostream.clips import overlay

    logo = tmp_path / "me.png"
    logo.write_bytes(b"png")
    c = cfg.load()
    c["thumbnail"] = dict(c["thumbnail"], channel_name="StrangerChan", logo=str(logo))
    monkeypatch.setattr(cfg, "load", lambda: cfg.Config(c))
    assert overlay.branding() == ("@StrangerChan", logo)

    c["thumbnail"] = dict(c["thumbnail"], channel_name="", logo="")
    assert overlay.branding() == ("", None), "an unset channel must draw nothing"


def test_a_run_keeps_the_branding_it_was_cut_with(tmp_path):
    from autostream.clips import overlay

    assert overlay.branding({"handle": "@Then", "logo": ""}) == ("@Then", None)
    assert overlay.handle_for("@already") == "@already"
    assert overlay.handle_for("  two  words ") == "@two words"


# --------------------------------------------------------- the log (#30)

def test_the_obs_password_never_reaches_the_log():
    """obsws-python logs `password='...'` at INFO, and the root logger is at
    INFO. Nineteen lines of a real password were found in a live install."""
    from autostream.__main__ import RedactSecrets

    rec = logging.LogRecord(
        "obsws_python.baseclient.ObsClient", logging.INFO, "", 0,
        "Connecting with parameters: host=%r port=%d password=%r timeout=%r",
        ("localhost", 4455, "hunter2-very-secret", 5), None)
    RedactSecrets().filter(rec)
    msg = rec.getMessage()
    assert "hunter2" not in msg
    assert "password='(removed)'" in msg and "port=4455" in msg


def test_diagnostics_scrub_overlay_tokens_and_logged_passwords():
    app = webui.Server.__new__(webui.Server)
    text = ("screens.ending_file = https://streamelements.com/overlay/"
            "5f0abc123/AbCdEf0123456789token\n"
            "Connecting with parameters: host='localhost' password='s3cret99'")
    out = app._scrub(text, {})
    assert "AbCdEf0123456789token" not in out
    assert "s3cret99" not in out
    assert "streamelements.com/overlay/5f0abc123/(removed)" in out


# ------------------------------------------------------- the page (#14 #21 #26 #15 #17 #16)

def test_every_switch_has_something_to_see_and_click():
    """Seven toggles on the Clips page were 0 px wide: `.switch-dot` has no
    CSS. A spoken line could never be switched on."""
    css = _ui("css")
    assert ".switch-dot" not in css
    for page in ("clips", "settings", "logs", "studio", "reel", "dashboard"):
        text = _ui(page)
        assert "switch-dot" not in text, page
    assert _ui("clips").count('<span class="switch-track"><span class="switch-thumb">') >= 7


def test_the_song_mark_nudge_reads_its_own_button():
    js = _ui("studio")
    line = next(ln for ln in js.splitlines() if "studio-sg-marknudge" in ln
                and "studio_sgNudgeMark" in ln)
    assert "b.getAttribute('data-d')" in line, line


def test_picking_a_stream_loads_that_streams_clips():
    js = _ui("clips")
    i = js.index("act === 'pick')")
    assert "clip_loadMade(clip_state.pick)" in js[i:i + 700]


def test_a_clip_with_edits_is_not_left_behind_when_it_ends():
    js = _ui("clips")
    i = js.index("vid.addEventListener('ended'")
    assert "clip_playerDirty()" in js[i:i + 900]
    j = js.index("function clip_playerStep(")
    assert "clip_playerDirty()" in js[j:j + 600]


def test_the_chosen_upload_privacy_is_not_put_back_every_tick():
    js = _ui("clips")
    i = js.index("var pv = clip_el('clip-up-privacy');")
    assert "dataset.chosen" in js[i:i + 300]


def test_the_upload_folder_pattern_knows_both_separators():
    js = _ui("clips")
    line = next(ln for ln in js.splitlines() if "clip_state.upFolder = mp.replace" in ln)
    assert r"[\\/]" in line, line


# ---------------------------------------------------------------- the rest

def test_the_version_is_sent_to_the_page(tmp_path):
    js = _ui("settings")
    assert "&& window.SHELL_BOOT &&" not in js, "SHELL_BOOT is a let; window never has it"
    src = (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")
    i = src.index('u.path == "/api/bootstrap"')
    assert '"version": __version__' in src[i:i + 600]


@pytest.mark.parametrize("path,value", [
    ("record.directory", "pw-directory"),
    ("record.directory", "C:\\Videos\nx"),
    ("obs.path", "obs64.exe"),
    ("thumbnail.logo", "C:\\nowhere\\logo.png"),
    ("clips.music", "C:\\nowhere\\song.flac"),
    ("screens.ending_file", "ending.mp4"),
    ("rules.web_token", "a"),
])
def test_a_setting_that_names_a_file_is_checked_when_saved(path, value):
    assert schema.validate(path, value), f"{path}={value!r} was accepted"


def test_a_web_token_can_still_be_cleared_or_set_properly():
    assert schema.validate("rules.web_token", "") is None
    assert schema.validate("rules.web_token", "x" * 16) is None
    assert schema.validate("screens.ending_file", "https://example.com/o") is None


def test_the_dead_dashboard_switch_is_gone_and_lan_is_real():
    assert "rules.web_dashboard" not in schema.FIELDS_BY_PATH
    assert "rules.web_lan" in schema.FIELDS_BY_PATH
    s = webui.Server("t" * 16, 8999, None, lan=False)
    assert s.url().startswith("http://127.0.0.1:")


def test_the_wizard_refuses_a_time_the_settings_page_would(monkeypatch):
    """"25:00" was saved as quiet hours, and the engine then quietly treated
    it as none at all."""
    from autostream import cfg
    from autostream.setup_flow import SetupFlow

    saved = {}
    monkeypatch.setattr(cfg, "save_fields", lambda f: saved.update(f))
    monkeypatch.setattr(cfg, "save_field", lambda *a: saved.update({a: 1}))
    out = SetupFlow().save_section("timing", {"arm_delay": 30, "quiet_from": "25:00",
                                              "quiet_to": "01:00"})
    assert out["ok"] is False and "24-hour" in out["error"]
    assert saved == {}
    out = SetupFlow().save_section("timing", {"arm_delay": -5})
    assert out["ok"] is False


def test_the_wizard_logo_placeholder_keeps_its_backslashes():
    js = _ui("setup")
    assert r'placeholder="C:\\Users\\you\\Pictures\\logo.png"' in js


def test_a_thumbnail_has_to_be_an_image(tmp_path):
    fake = tmp_path / "token.json"
    fake.write_text("{}", encoding="utf-8")
    assert webui._not_an_image(str(fake))
    lying = tmp_path / "win.png"
    lying.write_text("[fonts]", encoding="utf-8")
    assert webui._not_an_image(str(lying))
    from PIL import Image

    real = tmp_path / "real.png"
    Image.new("RGB", (4, 4)).save(real)
    assert webui._not_an_image(str(real)) is None


def test_a_frame_is_only_read_from_a_video(tmp_path):
    app = webui.Server.__new__(webui.Server)
    notes = tmp_path / "secrets.json"
    notes.write_text("{}", encoding="utf-8")
    png, err = app.clip_frame(str(notes), 1.0)
    assert png == b"" and err


def test_rescan_keeps_apps_added_by_hand(monkeypatch):
    from autostream import catalog

    mine = catalog.App(key="mine", name="Hand Added", path="C:/g/g.exe",
                       exe="handadded.exe", source="manual")
    found = catalog.App(key="cs2", name="Counter-Strike 2", exe="cs2.exe",
                        source="steam")
    saved = {}
    monkeypatch.setattr(catalog, "load", lambda: [mine])
    monkeypatch.setattr(catalog, "discover_all", lambda: [found])
    monkeypatch.setattr(catalog, "save", lambda apps: saved.update(apps=apps))
    from fakes import LiveServer

    srv = LiveServer()
    try:
        monkeypatch.setattr(srv.srv, "apps_payload", lambda: [])
        r = srv.post("/api/apps/scan", {})
    finally:
        srv.close()
    assert r.status == 200
    assert {a.name for a in saved["apps"]} == {"Hand Added", "Counter-Strike 2"}


def test_every_part_label_is_unique_in_its_drawer():
    from collections import Counter

    from autostream.clips import studio

    twice = [k for k, n in Counter((p.kind, p.label) for p in studio.PARTS).items()
             if n > 1]
    assert twice == []


def test_an_unreadable_intro_says_so_without_a_dangling_colon(tmp_path):
    from autostream.clips import intros

    f = tmp_path / "broken.mp4"
    f.write_bytes(b"nope")

    def fails(_p):
        raise RuntimeError("ffprobe.EXE failed (1):\n")

    with pytest.raises(ValueError) as e:
        intros.add(f, measure=fails)
    assert not str(e.value).rstrip().endswith(":")
    assert "failed (1)" not in str(e.value)


def test_the_installer_waits_for_an_upload(monkeypatch, tmp_path):
    from autostream.clips import upload as up

    app = webui.Server.__new__(webui.Server)
    app.engine = None
    inst = tmp_path / "AutoStream-setup.exe"
    inst.write_bytes(b"MZ")
    app._update_job = {"state": "ready", "path": str(inst)}
    monkeypatch.setattr(up.runner(), "busy", lambda: True)
    out = app.update_install()
    assert "uploading" in out.get("error", "")


def test_a_rescan_does_not_promise_a_quick_recut_it_will_not_do():
    src = (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")
    assert '"reused_kills": bool(opt.get("kills"))' in src


# ------------------------------------------------ the engine, off the tick

def _engine(phase=IDLE):
    from fakes import engine

    eng = engine(phase=phase)
    eng._marks = []
    eng._mark_seen = {}
    eng.yt = types.SimpleNamespace(watch_url=lambda b: f"https://youtu.be/{b}")
    return eng


def test_a_recording_made_outside_a_session_reaches_the_journal(monkeypatch):
    """Record pressed on the idle dashboard wrote a file nothing journalled."""
    from autostream import history

    rows = []
    monkeypatch.setattr(history, "append", rows.append)
    monkeypatch.setattr(history, "_probe_duration", lambda p: 12.0)
    monkeypatch.setattr(engine_mod.notify, "toast", lambda *a, **k: None)
    eng = _engine(IDLE)
    eng._start_recording = lambda: setattr(eng.state, "recording", True)
    eng.obs.stop_recording = lambda: "C:/v/2026-09-25 06-12-55.mp4"
    assert eng.toggle_recording("test") is True
    assert eng.toggle_recording("test") is False
    assert [r["recording_path"] for r in rows] == ["C:/v/2026-09-25 06-12-55.mp4"]


def test_every_file_of_a_session_gets_its_own_row(monkeypatch):
    """Stop recording, Record again: the journal kept only the newest file."""
    from autostream import history

    rows = []
    monkeypatch.setattr(history, "record_session",
                        lambda state, **kw: rows.append(kw["recording_path"]) or kw)
    eng = _engine(LIVE)
    eng._earlier_files = ({"path": "C:/v/first.mp4", "marks": []},)
    eng.state.broadcast_id = "bid-1"
    eng._journal("C:/v/second.mp4")
    assert rows == ["C:/v/first.mp4", "C:/v/second.mp4"]


def test_a_retitle_is_what_the_journal_remembers(monkeypatch):
    eng = _engine(LIVE)
    eng.state.broadcast_id = "bid-1"
    eng.state.current_game = "A"
    eng.state.current_key = "a.exe"
    eng.state.session_games = ["A"]
    eng.state.session_start = time.time()
    eng.yt = types.SimpleNamespace(retitle=lambda *a: None,
                                   watch_url=lambda b: b)
    eng._set_thumbnail = lambda: None
    eng._last_title = "A - first"
    from autostream.gameindex import GameHit

    hit = GameHit(key="b.exe", name="B", source="test")
    eng._switch_candidate = (hit.key, 0.0)
    eng._maybe_switch(hit)
    assert eng._last_title != "A - first"
    assert "B" in eng._last_title


def test_setup_says_how_long_it_waited_and_gives_the_link(monkeypatch, tmp_path):
    """"Waiting for your browser..." used to wait forever."""
    from autostream import paths, setup_flow, youtube

    monkeypatch.setattr(paths, "CLIENT_SECRET", tmp_path / "client.json")
    (tmp_path / "client.json").write_text("{}", encoding="utf-8")

    class WSGITimeoutError(Exception):
        pass

    def authorise(self, interactive=False, *, timeout=None, on_url=None):
        assert timeout and timeout <= 600
        on_url("https://accounts.google.com/o/oauth2/auth?x=1")
        raise WSGITimeoutError("Timed out waiting for response")

    monkeypatch.setattr(youtube.YouTube, "authorise", authorise)
    flow = setup_flow.SetupFlow()
    out = flow.authorise()
    assert out["ok"] is False
    assert out["url"].startswith("https://accounts.google.com/")
    assert flow.auth_link()["waiting"] is False, "the listener was left holding"


def test_the_prompt_hands_over_the_sign_in_link():
    from autostream.youtube import _Prompt

    got = []
    msg = _Prompt("Opening your browser.", got.append)
    assert msg.format(url="https://x/y") == "Opening your browser."
    assert got == ["https://x/y"]


def test_song_marks_move_with_the_part():
    """Moving the part from 2:12 to 0:56 left every mark at 2:12, outside the
    part and drawn nowhere. The marks are song seconds that travel with a MOVE
    of the part -- and only a move: resizing it by an edge used to drag every
    mark off the beat it was tapped on."""
    js = _ui("studio")
    i = js.index("function studio_sgMovePart(start)")
    assert "sg.marks = sg.marks.map(m => Math.round((m + dt) * 1000) / 1000)" in js[i:i + 900]
    # every whole-part move goes through it
    for fn in ("function studio_sgNudge(", "function studio_sgSnapBar()", "function studio_sgAtDrop()",
               "function studio_sgPointer("):
        j = js.index(fn)
        assert "studio_sgMovePart(" in js[j:j + 2500], fn
    # and nothing infers a move from a changed start any more
    assert "marksAt" not in js
