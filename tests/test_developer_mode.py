r"""Developer Mode: the switch, the button it adds, and the run behind it.

OFF BY DEFAULT AND GATED TWICE. The setting hides the button, which is a
courtesy; the run route refuses the flag, which is what makes the setting mean
something. A page that stopped drawing a control is not a permission check.

THE RUN IS THE REAL RUN. No sample, no shortened scan, no stub encoder -- the
whole value of a diagnostic is that what it measures is what a real run does,
and the failure it was built for (ffmpeg exiting 255 on an AMD card before it
reads a frame) only happens on the real path. So the only thing the flag
changes is that the job carries a recorder instead of the no-op one.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from autostream import cfg, paths, schema
from autostream.clips import diag, jobs

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ------------------------------------------------------------- the setting

def test_it_is_off_until_somebody_turns_it_on():
    assert cfg.DEFAULTS["ui"]["developer_mode"] is False


def test_it_is_a_setting_people_can_find():
    """Written only into DEFAULTS it would be a hidden flag, which is a
    feature nobody can use and nobody can turn off again."""
    paths_in_schema = {f["path"] for s in schema.CONFIG_SCHEMA for f in s["fields"]}
    assert "ui.developer_mode" in paths_in_schema


def test_it_sits_with_the_log_settings_and_not_under_advanced():
    """Advanced is "written by setup or by the daemon itself, change these
    only if you know exactly why" -- things that break the app. This breaks
    nothing; it adds a button."""
    home = next(s for s in schema.CONFIG_SCHEMA
                for f in s["fields"] if f["path"] == "ui.developer_mode")
    assert home["id"] == "logging"
    assert home.get("advanced") is not True


def test_the_help_says_what_it_actually_adds():
    """A toggle called "Developer mode" with no sentence under it is a dare."""
    field = next(f for s in schema.CONFIG_SCHEMA for f in s["fields"]
                 if f["path"] == "ui.developer_mode")
    assert "diagnostic" in field["help"].lower()


# ------------------------------------------------------- the job's recorder

def test_an_ordinary_job_carries_the_recorder_that_does_nothing(tmp_path):
    job = jobs.ClipJob(tmp_path / "rec.mp4", game="Testing", game_key=None,
                       outdir=tmp_path / "out", options={})
    assert job.diag is diag.OFF
    assert job.snapshot()["diagnostic_run"] is False


def test_asking_for_one_gives_the_job_a_real_recorder(tmp_path):
    job = jobs.ClipJob(tmp_path / "rec.mp4", game="Testing", game_key=None,
                       outdir=tmp_path / "out", options={"diagnostic": True})
    assert job.diag.on is True
    assert job.snapshot()["diagnostic_run"] is True


def test_a_job_built_without_its_constructor_still_has_one():
    """Several tests build a ClipJob with __new__ to exercise snapshot and
    cancel without a recording. The recorder is read from `run`, from
    `snapshot` and from a dozen places inside `_run`, so it lives on the
    CLASS -- the first version of this turned every one of those into an
    AttributeError."""
    bare = jobs.ClipJob.__new__(jobs.ClipJob)
    assert bare.diag is diag.OFF
    assert bare.diag_path == ""


# ------------------------------------------- it is written even on a failure

@pytest.fixture
def logs(tmp_path, monkeypatch):
    """Send reports somewhere throwaway rather than into the repo's logs."""
    where = tmp_path / "logs"
    monkeypatch.setattr(paths, "LOGS_DIR", where)
    return where / "diagnostics"


def _failing_job(tmp_path, **opts):
    """A run that cannot get past its first line: the source is not there.

    Chosen because it needs no ffmpeg and no footage, and because it fails
    in `_run` the same way a real failure does -- through the generic
    handler in `run`, into the `finally` that writes the report.
    """
    return jobs.ClipJob(tmp_path / "not-here.mp4", game="Testing",
                        game_key=None, outdir=tmp_path / "out", options=opts)


def _report(folder):
    files = sorted(folder.glob("clip-diagnostic-*.json"))
    assert len(files) == 1, f"expected one report, found {len(files)}"
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_a_failed_run_still_writes_its_report(tmp_path, logs):
    """THE CASE IT EXISTS FOR. A diagnostic produced only on success
    describes every run except the one somebody wanted explained."""
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    assert job.state == "failed"
    body = _report(logs)
    assert body["outcome"] == "failed"


def test_the_report_names_the_error_and_keeps_its_traceback(tmp_path, logs):
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    body = _report(logs)
    assert body["errors"], "a failed run recorded no error"
    assert body["errors"][0]["type"] == "FileNotFoundError"
    assert "Traceback" in body["errors"][0]["traceback"]


def test_the_stage_it_died_in_is_the_one_left_open(tmp_path, logs):
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    last = _report(logs)["stages"][-1]
    assert last["ok"] is False
    assert "probe the source" in last["name"]


def test_the_report_says_what_the_machine_is(tmp_path, logs):
    """Gathered at the start of the run, so it describes the machine the run
    actually had rather than the one it finished on."""
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    sysinfo = _report(logs)["system"]
    assert sysinfo.get("os")
    assert "nvenc" in (sysinfo.get("gpu") or {})


def test_the_page_is_told_where_the_report_went(tmp_path, logs):
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    snap = job.snapshot()
    assert snap["diagnostic"].endswith(".json")
    assert pathlib.Path(snap["diagnostic"]).is_file()


def test_an_ordinary_failed_run_writes_nothing(tmp_path, logs):
    """Everybody else's runs are unchanged, including the ones that fail."""
    job = _failing_job(tmp_path)
    job.run()
    assert job.state == "failed"
    assert job.diag_path == ""
    assert not logs.exists()


def test_the_recorder_is_not_left_current_afterwards(tmp_path, logs):
    """It is a module global, so one left set would collect the NEXT run's
    ffmpeg calls into a report that was already written."""
    _failing_job(tmp_path, diagnostic=True).run()
    assert diag.active() is None


def test_a_report_that_cannot_be_written_does_not_fail_the_run(tmp_path,
                                                               monkeypatch):
    """Rule one. The diagnostic is the last thing to touch a run and must
    not be the thing that decides its outcome."""
    monkeypatch.setattr(paths, "LOGS_DIR", pathlib.Path("Z:/no/such/place"))
    monkeypatch.setattr(diag.Recorder, "write",
                        lambda self, folder: (_ for _ in ()).throw(OSError("nope")))
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    assert job.state == "failed"          # the run's own failure, not the write's
    assert job.error and "not-here.mp4" in job.error
    assert diag.active() is None


def test_a_gpu_probe_that_hangs_up_the_driver_does_not_change_the_outcome(
        tmp_path, logs, monkeypatch):
    """Gathering the machine block runs ffmpeg three or four times, twice
    through the graphics driver -- on a PC whose graphics stack may well be
    the thing being diagnosed. That must cost the report, not the clips."""
    monkeypatch.setattr(diag, "system_info",
                        lambda: (_ for _ in ()).throw(OSError("the driver went")))
    job = _failing_job(tmp_path, diagnostic=True)
    job.run()
    assert job.state == "failed"
    assert "not-here.mp4" in (job.error or "")   # its own failure, not the probe's


# -------------------------------------------------------- the server's gate

def _run_body(**extra):
    return {"source": "", "recording_path": "", "plan_only": True, **extra}


def test_the_flag_is_refused_while_developer_mode_is_off(monkeypatch):
    """Hiding the button is a courtesy to the user. This is the check."""
    src = (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")
    i = src.index('if body.get("diagnostic")')
    line = src[i:src.index("\n", i)]
    assert "developer_mode" in line, (
        "the run route takes the diagnostic flag without asking whether "
        "developer mode is on: " + line)


def test_the_clips_page_is_told_whether_it_is_on():
    src = (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")
    assert '"developer": bool(getattr(cfg_now.ui, "developer_mode", False))' in src


# ------------------------------------------------------------ the button

@pytest.fixture(scope="module")
def clips_src() -> str:
    return (ROOT / "autostream" / "ui" / "clips.py").read_text(encoding="utf-8")


def test_the_button_is_on_the_style_page(clips_src):
    i = clips_src.index('id="clip-options" data-cstep="style"')
    j = clips_src.index('id="clip-progress"')
    assert 'id="clip-diag"' in clips_src[i:j], (
        "Run diagnostic is not inside the style card")


def test_it_is_hidden_until_the_page_is_told_otherwise(clips_src):
    """A control everybody sees and nobody may use is a question everybody
    has to ask. It ships hidden and the render shows it."""
    i = clips_src.index('id="clip-diag"')
    markup = clips_src[clips_src.rindex("<button", 0, i):i]
    assert "hide" in markup
    assert "clip_show('clip-diag', !!clip_state.dev)" in clips_src


def test_it_posts_to_the_same_route_as_make_clips(clips_src):
    """Not a second code path. The point of the diagnostic is that it
    measures what an ordinary run does."""
    i = clips_src.index("async function clip_runDiag")
    body = clips_src[i:clips_src.index("async function clip_run()", i)]
    assert "clip_runBody(s)" in body
    assert "'/api/clips/run'" in body
    assert "body.diagnostic = true" in body


def test_the_report_is_offered_however_the_run_ended(clips_src):
    """done, failed or cancelled: the failed one is the whole reason the
    button exists."""
    assert "clip_show('clip-diagdone', !!j.diagnostic_run)" in clips_src
    i = clips_src.index("clip_show('clip-diagdone'")
    before = clips_src[:i]
    # It is rendered after the early return for a run that has not finished,
    # and that return is the only gate -- so it is reached for every
    # terminal state rather than only for `done`.
    assert "if (!done) return;" in before
