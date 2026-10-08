r"""Developer Mode's clip diagnostic: what it records, and what it must not do.

THE RULE THAT MATTERS MOST IS THE NEGATIVE ONE. A diagnostic that turns a
working clip run into a failed one is worse than no diagnostic at all, so a
large part of this file is about the recorder being handed rubbish -- an
unopened stage, a path that cannot be written, an exception with no traceback,
a folder on a drive that is not there -- and returning rather than raising.

THE SECOND IS THAT IT HAS TO EXIST AFTER A FAILURE. The run it was asked
about is, by definition, the run that did not work.

THE THIRD IS THAT IT CARRIES NO SECRETS. Nothing here reads the config, the
token store or the environment; the one thing that leaks by accident is the
user's account name, which is in every file path, so that is checked directly.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autostream.clips import diag

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def leaks_home(text: str) -> bool:
    r"""Whether the user's home DIRECTORY survived into `text`.

    The home PATH, not the account name on its own. This account is called
    "user", which is a substring of "%USERPROFILE%" -- so a search for the
    name reports a leak in every correctly redacted report, and a test that
    can only fail is worse than no test. Both separators and JSON's doubled
    backslashes are checked, because the report is read as a file.
    """
    home = str(Path.home())
    forms = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    low = text.lower()
    return any(f.lower() in low for f in forms)


@pytest.fixture
def rec():
    return diag.Recorder(job="2026-10-05_Testing", source=r"C:\v\rec.mp4",
                         game="Testing", options={"style": "shortform"})


@pytest.fixture(autouse=True)
def no_recorder_left_behind():
    """The recorder is a module global. One left set by a failing test would
    collect the next test's processes into a dead object -- and, worse, would
    hide a bug where the job forgets to clear it."""
    yield
    diag.set_active(None)


# ------------------------------------------------------- the off switch

def test_an_ordinary_run_carries_a_recorder_that_does_nothing():
    """Instrumentation guarded by `if self.diag:` at forty call sites is
    instrumentation somebody will forget to guard."""
    assert diag.OFF.on is False
    diag.OFF.stage("x")
    diag.OFF.note("a", 1)
    diag.OFF.event("hello")
    diag.OFF.error(ValueError("no"))
    diag.OFF.output("clip", "x.mp4")
    diag.OFF.finish("done")
    assert diag.OFF.write("nowhere") == ""


def test_the_off_recorder_writes_no_file(tmp_path):
    diag.OFF.write(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_nothing_is_recorded_when_no_diagnostic_is_running():
    """note_process is called by tools.run on EVERY ffmpeg in the app,
    diagnostic or not. With nobody recording it has to be a return."""
    assert diag.active() is None
    diag.note_process(["ffmpeg"], 1, "boom", 0.1)      # must not raise


# --------------------------------------------------------------- stages

def test_a_stage_is_timed_and_closed_by_the_next_one(rec):
    rec.stage("one")
    rec.stage("two")
    rec.end_stages(ok=True)
    names = [s["name"] for s in rec.report()["stages"]]
    assert names == ["one", "two"]
    assert all(s["seconds"] is not None for s in rec.report()["stages"])


def test_the_stage_still_open_at_the_end_is_the_one_it_died_in(rec):
    """The whole reason stages are marks rather than context managers: the
    run does not get to tell us which stage it failed in, so the structure
    has to say it."""
    rec.stage("scan")
    rec.stage("cut")
    rec.error(RuntimeError("ffmpeg fell over"))
    rec.finish("failed", "ffmpeg fell over")
    body = rec.report()
    last = body["stages"][-1]
    assert last["name"] == "cut"
    assert last["ok"] is False


def test_reporting_twice_does_not_close_the_open_stage_twice(rec):
    """`report` is called by `write`, and the page may ask for one as well."""
    rec.stage("scan")
    first = rec.report()
    second = rec.report()
    assert len(first["stages"]) == len(second["stages"]) == 1


def test_a_stage_says_when_it_began_as_well_as_how_long_it_took(rec):
    """Two different questions. "the cut took 40s" and "the cut began 11m12s
    in" are both asked of a slow run, and only the second lines the report
    up against the app's own log."""
    rec.stage("one")
    rec.stage("two")
    rec.end_stages(ok=True)
    stages = rec.report()["stages"]
    assert all("at" in s for s in stages)
    assert stages[0]["at"] <= stages[1]["at"]


def test_a_note_lands_on_the_stage_that_learned_it_and_at_the_top(rec):
    rec.stage("scan")
    rec.note("kills_found", 12)
    body = rec.report()
    assert body["facts"]["kills_found"] == 12
    assert body["stages"][0]["notes"]["kills_found"] == 12


def test_a_note_with_no_stage_open_is_still_kept(rec):
    rec.note("system", {"os": "Windows"})
    assert rec.report()["facts"]["system"] == {"os": "Windows"}


def test_ending_stages_when_none_is_open_is_not_an_error(rec):
    rec.end_stages(ok=True)
    assert rec.report()["stages"] == []


# ------------------------------------------------------------ processes

def test_a_process_is_recorded_with_its_exit_code_and_stderr(rec):
    rec.stage("cut")
    rec.process(["C:/ff/ffmpeg.exe", "-i", "a.mp4"], 1, "line one\nline two", 2.5)
    row = rec.report()["processes"][0]
    assert row["exe"] == "ffmpeg.exe"
    assert row["exit"] == 1
    assert row["stage"] == "cut"
    assert "line two" in row["stderr"]
    assert row["seconds"] == 2.5


def test_a_successful_process_is_recorded_too(rec):
    """A failed run's evidence is usually what the SUCCESSFUL calls did
    before it -- which resolution was asked for, which encoder was used."""
    rec.process(["ffprobe", "x.mp4"], 0, "", 0.2)
    assert rec.report()["process_summary"] == {"total": 1, "failed": 0, "kept": 1}


def test_the_cap_drops_successes_and_never_the_failure(monkeypatch, rec):
    """A fifty-clip montage is hundreds of invocations. The cap keeps the
    file attachable -- but dropping the one non-zero exit among them would
    remove the only thing the report was opened for."""
    monkeypatch.setattr(diag, "MAX_PROCESSES", 3)
    for _ in range(20):
        rec.process(["ffmpeg"], 0, "", 0.1)
    rec.process(["ffmpeg"], 255, "no NVENC capable devices found", 0.1)
    body = rec.report()
    assert body["process_summary"]["total"] == 21
    assert body["process_summary"]["failed"] == 1
    kept = body["processes"]
    assert len(kept) == 4                      # 3 successes plus the failure
    assert kept[-1]["exit"] == 255
    assert "NVENC" in kept[-1]["stderr"]


def test_a_very_long_command_line_is_cut(rec):
    """A reel's filter graph is tens of thousands of characters and is
    already written to a file by the code that builds it."""
    rec.process(["ffmpeg", "-filter_complex", "x" * 50_000], 0, "", 0.1)
    assert len(rec.report()["processes"][0]["args"]) < 1500


def test_stderr_is_kept_to_its_tail(monkeypatch, rec):
    monkeypatch.setattr(diag, "STDERR_LINES", 5)
    rec.process(["ffmpeg"], 1, "\n".join(f"line {i}" for i in range(100)), 0.1)
    tail = rec.report()["processes"][0]["stderr"].splitlines()
    assert len(tail) == 5
    assert tail[-1] == "line 99"


def test_an_empty_argument_list_does_not_crash_the_recorder(rec):
    rec.process([], 1, "", 0.0)
    assert rec.report()["processes"][0]["exe"] == ""


def test_bytes_out_are_recorded_where_they_are_given(rec):
    """ffmpeg_raw does not raise on a non-zero exit -- it returns empty
    stdout, which every caller reads as "no frames" rather than "it
    refused". The pair of numbers is what tells the two apart."""
    rec.process(["ffmpeg"], 255, "Impossible to convert", 0.3, stdout_bytes=0)
    row = rec.report()["processes"][0]
    assert row["stdout_bytes"] == 0 and row["exit"] == 255


# --------------------------------------------------------------- errors

def test_an_error_is_recorded_with_its_traceback(rec):
    rec.stage("cut")
    try:
        raise RuntimeError("ffmpeg failed (255)")
    except RuntimeError as e:
        rec.error(e)
    err = rec.report()["errors"][0]
    assert err["type"] == "RuntimeError"
    assert "ffmpeg failed (255)" in err["message"]
    assert "RuntimeError" in err["traceback"]
    assert err["stage"] == "cut"


def test_an_exception_that_was_never_raised_still_records(rec):
    """`raise X` is not the only way one reaches here; a handler may pass an
    exception it constructed. No __traceback__ must not be a crash."""
    rec.error(ValueError("built, not raised"))
    assert rec.report()["errors"][0]["type"] == "ValueError"


# -------------------------------------------------------------- outputs

def test_a_file_that_is_there_is_recorded_with_its_size(rec, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x" * 1234)
    rec.output("master", f)
    row = rec.report()["outputs"][0]
    assert row["exists"] is True and row["bytes"] == 1234


def test_a_file_that_is_not_there_says_so(rec, tmp_path):
    """A zero-byte file and a missing one are different failures, and both
    read as "no clips" from the outside."""
    rec.output("master", tmp_path / "gone.mp4")
    row = rec.report()["outputs"][0]
    assert row["exists"] is False and row["bytes"] is None


# ------------------------------------------------------------- redaction

def test_the_home_directory_is_shaped_out_of_a_path():
    home = str(Path.home())
    assert diag.redact(home + r"\Videos\x.mp4") == r"%USERPROFILE%\Videos\x.mp4"


def test_it_is_shaped_with_either_separator():
    home = str(Path.home()).replace("\\", "/")
    assert "%USERPROFILE%" in diag.redact(home + "/Videos/x.mp4")


def test_a_path_inside_a_python_repr_is_shaped_too():
    r"""THE THIRD LEAK, and the one that mattered most, because it is the
    text of an OSError. FileExistsError embeds the filename repr'd, so its
    message reads C:\\Users\\sam\\... with the backslashes DOUBLED -- which
    matched none of the spellings redaction knew. It appeared verbatim in
    the stage error, in the error list and in the human summary of a run
    that failed on a file, which is most runs that fail.
    """
    text = str(FileExistsError(17, "exists", str(Path.home() / "a" / "b")))
    shaped = diag.redact(text)
    assert not leaks_home(shaped), shaped
    assert "%USERPROFILE%" in shaped


def test_redaction_walks_into_lists_and_dicts():
    home = str(Path.home())
    got = diag.redact({"a": [home + r"\x"], "b": {"c": home}})
    assert got == {"a": [r"%USERPROFILE%\x"], "b": {"c": "%USERPROFILE%"}}


def test_numbers_and_booleans_come_through_untouched():
    assert diag.redact({"n": 3, "b": True, "z": None}) == {"n": 3, "b": True, "z": None}


def test_the_account_name_is_nowhere_in_a_written_report(tmp_path):
    """The one personal thing a clip run's paths carry, in every one of them."""
    home = Path.home()
    rec = diag.Recorder(job="j", source=home / "Videos" / "rec.mp4", game="X")
    rec.stage("cut")
    rec.process(["ffmpeg", "-i", str(home / "Videos" / "rec.mp4")], 1,
                f"could not open {home}\\Videos\\rec.mp4", 0.1)
    rec.output("master", home / "Videos" / "out.mp4")
    rec.finish("failed")
    text = Path(rec.write(tmp_path)).read_text(encoding="utf-8")
    assert not leaks_home(text), "the user's home folder reached the report"
    assert "%USERPROFILE%" in text


def test_a_stage_note_is_redacted_as_well_as_the_fact_it_becomes(tmp_path):
    """THE FIRST LEAK. `note` writes to two places -- `facts` and the open
    stage's `notes` -- and only the first was being shaped, so every
    diagnostic carried the user's folder under `stages[].notes`."""
    rec = diag.Recorder(job="j")
    rec.stage("cut")
    rec.note("folder", str(Path.home() / "Videos" / "clips"))
    body = rec.report()
    assert "%USERPROFILE%" in body["stages"][0]["notes"]["folder"]
    assert not leaks_home(json.dumps(body["stages"]))


def test_a_stages_failure_message_is_redacted(tmp_path):
    """THE SECOND. A stage's `error` was written straight from the
    exception's text, and a FileNotFoundError's text is a full path."""
    rec = diag.Recorder(job="j")
    rec.stage("probe the source")
    rec.end_stages(ok=False, error=f"recording not found: {Path.home()}/r.mp4")
    assert "%USERPROFILE%" in rec.report()["stages"][0]["error"]


def test_the_human_summary_cannot_reprint_what_the_body_removed():
    """THE THIRD, and the reason the other two were worth finding twice: the
    summary is rendered from the body, so anything unshaped in the body was
    printed again in the first thing a reader sees."""
    rec = diag.Recorder(job="j", source=Path.home() / "Videos" / "rec.mp4")
    rec.stage("cut")
    rec.process(["ffmpeg", "-i", str(Path.home() / "r.mp4")], 1,
                f"cannot open {Path.home()}/r.mp4", 0.1)
    rec.finish("failed")
    assert not leaks_home(rec.report()["summary"])


def test_bulk_options_are_counted_rather_than_copied(tmp_path):
    """Three hundred kill timestamps in the options block would bury the
    half dozen settings a reader is actually looking for."""
    rec = diag.Recorder(options={"kills": [{"time": i} for i in range(300)],
                                 "style": "shortform"})
    body = rec.report()
    assert body["options"]["kills"] == "(300 items)"
    assert body["options"]["style"] == "shortform"


# ---------------------------------------------------------- the one file

def test_it_writes_exactly_one_file(tmp_path):
    rec = diag.Recorder(job="j")
    rec.finish("done")
    where = rec.write(tmp_path)
    assert Path(where).is_file()
    assert len(list(tmp_path.iterdir())) == 1


def test_the_file_is_json_a_program_can_read(tmp_path):
    rec = diag.Recorder(job="j", source="x.mp4", game="Testing")
    rec.stage("scan")
    rec.note("kills_found", 4)
    rec.finish("done")
    body = json.loads(Path(rec.write(tmp_path)).read_text(encoding="utf-8"))
    assert body["kind"] == "autostream-clip-diagnostic"
    assert body["facts"]["kills_found"] == 4


def test_the_human_summary_is_the_first_thing_in_it(tmp_path):
    """Whoever opens this is looking for what broke, not for a schema."""
    rec = diag.Recorder(job="j")
    rec.finish("failed", "ffmpeg not found")
    text = Path(rec.write(tmp_path)).read_text(encoding="utf-8")
    body = json.loads(text)
    assert list(body)[0] == "summary"
    assert "AutoStream clip diagnostic" in body["summary"]


def test_the_summary_is_built_from_the_body_it_ships_with():
    """Assembled separately it drifts from the data under it, and then the
    first thing the reader sees is the thing that is wrong."""
    rec = diag.Recorder(job="j")
    rec.stage("cut")
    rec.process(["ffmpeg"], 255, "no NVENC capable devices", 0.4)
    rec.error(RuntimeError("the cut failed"))
    rec.finish("failed")
    body = rec.report()
    text = body["summary"]
    assert "failed" in text
    assert "cut" in text
    assert "no NVENC capable devices" in text
    assert "the cut failed" in text


def test_a_summary_of_a_run_that_reached_nothing_still_renders():
    rec = diag.Recorder()
    assert "no stage was reached" in diag.summarise(rec.report())


def test_a_folder_that_cannot_be_written_gives_an_empty_path_not_a_crash():
    """Rule one. This is called from the job's `finally`."""
    assert diag.Recorder(job="j").write("Z:/not/a/drive/on/this/pc") == ""


def test_a_report_full_of_objects_json_cannot_name_is_still_written(tmp_path):
    """`note` takes whatever a stage hands it, and a stage that hands it a
    Path or a dataclass must not cost the whole report."""
    rec = diag.Recorder(job="j")
    rec.note("where", Path("x.mp4"))
    rec.note("prof", object())
    assert Path(rec.write(tmp_path)).is_file()


def test_two_reports_in_the_same_second_do_not_overwrite_each_other(tmp_path,
                                                                    monkeypatch):
    """MEASURED, NOT IMAGINED. The stamp is accurate to the second, and six
    diagnostic runs driven back to back -- a missing file, a truncated file
    and a zero-byte file all fail in well under one -- produced four files.
    Two reports had been written over, and the survivor is the later one,
    which is not even the one most likely to be wanted."""
    monkeypatch.setattr(diag.time, "strftime", lambda *a, **k: "2026-10-05-120000")
    first = diag.Recorder(job="a").write(tmp_path)
    second = diag.Recorder(job="b").write(tmp_path)
    assert first != second
    assert len(list(tmp_path.iterdir())) == 2


def test_a_hundred_reports_in_one_second_still_each_get_a_name(tmp_path,
                                                               monkeypatch):
    """The uniquifier gives up counting at some point; what it must not do
    is start returning a name it has already returned."""
    monkeypatch.setattr(diag.time, "strftime", lambda *a, **k: "2026-10-05-120000")
    names = {diag.Recorder(job=str(i)).write(tmp_path) for i in range(120)}
    assert "" not in names
    assert len(names) == 120


# ------------------------------------------------ what the machine is

def test_system_info_answers_something_for_every_key():
    got = diag.system_info()
    for key in ("os", "cpu_count", "python", "autostream", "memory_gb",
                "ffmpeg", "ffprobe", "gpu"):
        assert key in got, key


def test_system_info_survives_a_check_that_blows_up(monkeypatch):
    """It runs at the START of a diagnostic run. A report that could not be
    gathered because one probe raised is a report nobody gets."""
    monkeypatch.setattr(diag, "gpu_info",
                        lambda: (_ for _ in ()).throw(OSError("no driver")))
    got = diag.system_info()
    assert "unavailable" in str(got["gpu"])


def test_memory_is_reported_as_a_peak_not_a_snapshot():
    """A scan holds frames for a thread pool and a reel builds its filter
    graph in memory; both are long gone by the time a run ends, so the
    number at the end says nothing about what the run needed."""
    got = diag.memory_used()
    if not got:
        pytest.skip("no memory counters on this platform")
    assert got["peak_mb"] >= got["now_mb"]


def test_disk_space_is_reported_for_a_real_folder(tmp_path):
    got = diag.disk_for(tmp_path)
    assert got["free_gb"] > 0 and got["total_gb"] > 0


def test_disk_space_for_a_path_that_cannot_be_asked_about_is_not_a_crash():
    """Which paths answer is not something this can know -- a mapped drive,
    a disconnected share, a sandbox. What it must do either way is come back
    with a dict rather than take the report down with it."""
    # chr(0), not an escape in the source: Python refuses to compile a file
    # with a real null byte in it, which is how this test first failed.
    got = diag.disk_for(chr(0) + ":/not/askable")
    assert isinstance(got, dict)
    assert "error" in got or "free_gb" in got


def test_a_tool_that_is_not_installed_reports_why():
    got = diag.tool_version("definitely-not-a-real-binary")
    assert got["found"] is False and got["why"]


def test_missing_tesseract_is_not_reported_as_missing_ffmpeg(monkeypatch):
    """FROM A REAL REPORT: a machine without Tesseract got a "why" telling
    the reader to `winget install --id Gyan.FFmpeg`. tool_version asked the
    ffmpeg finder for it, whose error is about ffmpeg."""
    from autostream.clips import deps

    def missing():
        raise deps.ToolMissing("Tesseract OCR was not found ... "
                               "UB-Mannheim.TesseractOCR")

    monkeypatch.setattr(deps, "tesseract", missing)
    got = diag.tool_version("tesseract")
    assert got["found"] is False
    assert "Gyan.FFmpeg" not in got["why"]
    assert "Tesseract" in got["why"]


# ------------------------------------------------- the process choke point

def test_tools_run_reports_to_whoever_is_recording(tmp_path):
    """Every external process in a clip run goes through tools.run, which is
    why the recorder is told there rather than at forty call sites."""
    from autostream.clips import tools

    rec = diag.Recorder(job="j")
    diag.set_active(rec)
    try:
        tools.run(["cmd", "/c", "exit", "0"])
    finally:
        diag.set_active(None)
    assert rec.report()["process_summary"]["total"] == 1


def test_a_process_that_failed_is_recorded_before_the_error_is_raised():
    """tools.run raises on a non-zero exit. Recording after the raise would
    mean the only process worth seeing is the only one missing."""
    from autostream.clips import tools

    rec = diag.Recorder(job="j")
    diag.set_active(rec)
    try:
        with pytest.raises(RuntimeError):
            tools.run(["cmd", "/c", "exit", "3"])
    finally:
        diag.set_active(None)
    assert rec.report()["processes"][0]["exit"] == 3


def test_a_recorder_that_throws_cannot_break_a_clip_run(monkeypatch):
    """Rule one, at the one place the app's own code calls into this on a
    hot path."""
    from autostream.clips import tools

    class Broken(diag.Recorder):
        def process(self, *a, **k):
            raise MemoryError("boom")

    diag.set_active(Broken())
    try:
        assert tools.run(["cmd", "/c", "exit", "0"]).returncode == 0
    finally:
        diag.set_active(None)
