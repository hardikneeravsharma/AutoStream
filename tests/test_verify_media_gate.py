r"""When a build has to measure the detectors, and when it does not.

TIER 4 IS MOST OF A RELEASE BUILD'S WALL CLOCK. It decodes real footage and
runs real encodes, and it was running on every `-Dist` build -- half an hour
spent proving that a change to the settings page had not moved a detector.

So verify.ps1 asks first. The rule is a line through the tree: `autostream\
clips\` and tier 4's own files are what it measures, and everything else --
the dashboard, the settings schema, OBS, the platform seam, the installer --
sits on the other side of it.

THE DANGEROUS ANSWER IS THE FALSE NEGATIVE. A needless half hour is a slow
build. Skipping tier 4 when it mattered ships a detector nobody measured, so
every case the function cannot answer -- no git, no tag, a git call that
fails -- has to come back "run it". Most of what is below is that direction.

The function is lifted out of the real script by its markers rather than
copied here, so this cannot pass against a rule that has since changed.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify.ps1"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


pytestmark = pytest.mark.skipif(
    not shutil.which("powershell") or not shutil.which("git"),
    reason="needs powershell and git")


@pytest.fixture(scope="module")
def decider() -> str:
    """The real `$MediaPaths` and `Test-MediaNeeded`, as text."""
    src = VERIFY.read_text(encoding="utf-8-sig")
    start = src.index("$MediaPaths = @(")
    end = src.index("# ---- tiers 1-3")
    return src[start:end]


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   creationflags=NO_WINDOW)


@pytest.fixture
def repo(tmp_path) -> pathlib.Path:
    """A throwaway checkout with one release tag on it."""
    r = tmp_path / "repo"
    (r / "autostream" / "clips").mkdir(parents=True)
    (r / "tests" / "verify").mkdir(parents=True)
    (r / "autostream" / "clips" / "detect.py").write_text("x", encoding="utf-8")
    (r / "autostream" / "webui.py").write_text("x", encoding="utf-8")
    (r / "tests" / "verify" / "test_media.py").write_text("x", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "first")
    _git(r, "tag", "v1.0.0")
    return r


def ask(repo: pathlib.Path, decider: str, tmp_path) -> dict:
    """Run the real decision function against `repo`. -> its answer."""
    harness = tmp_path / "ask.ps1"
    harness.write_text(
        decider
        + "\n$r = Test-MediaNeeded\n"
          "[Console]::Out.Write((@{ Needed = [bool]$r.Needed; Why = [string]$r.Why;"
          " Files = @($r.Files) } | ConvertTo-Json -Compress -Depth 4))\n",
        encoding="utf-8")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(harness)],
        cwd=repo, capture_output=True, text=True, timeout=120,
        creationflags=NO_WINDOW)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    # ConvertTo-Json gives a bare string for a one-item array.
    if isinstance(got.get("Files"), str):
        got["Files"] = [got["Files"]]
    got["Files"] = got.get("Files") or []
    return got


# ------------------------------------------------- it is needed when it is

def test_touching_a_detector_buys_the_half_hour(repo, decider, tmp_path):
    (repo / "autostream" / "clips" / "detect.py").write_text("y", encoding="utf-8")
    got = ask(repo, decider, tmp_path)
    assert got["Needed"] is True
    assert "autostream/clips/detect.py" in got["Files"]


def test_a_new_file_in_the_pipeline_counts(repo, decider, tmp_path):
    """Untracked, because the build is made from the working tree."""
    (repo / "autostream" / "clips" / "loudness.py").write_text("y", encoding="utf-8")
    assert ask(repo, decider, tmp_path)["Needed"] is True


def test_an_uncommitted_edit_counts(repo, decider, tmp_path):
    """A detector edited and not yet committed is a detector this build
    contains. Comparing only committed work would miss it."""
    (repo / "autostream" / "clips" / "detect.py").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")                       # staged, not committed
    assert ask(repo, decider, tmp_path)["Needed"] is True


def test_a_committed_edit_counts_too(repo, decider, tmp_path):
    (repo / "autostream" / "clips" / "detect.py").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "changed the detector")
    assert ask(repo, decider, tmp_path)["Needed"] is True


def test_it_looks_back_to_the_TAG_and_not_to_the_last_commit(repo, decider,
                                                             tmp_path):
    """THE REASON THE BASELINE IS THE TAG. A branch that rewrote the
    detector in its first commit and tidied a comment in its sixth would,
    measured against HEAD~1, skip the tier that exists to catch it."""
    (repo / "autostream" / "clips" / "detect.py").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "rewrote the detector")
    for i in range(5):
        (repo / "README.md").write_text(f"doc {i}", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"docs {i}")
    assert ask(repo, decider, tmp_path)["Needed"] is True


def test_tier_fours_own_tests_count(repo, decider, tmp_path):
    """A change to what it measures WITH is a change to the measurement."""
    (repo / "tests" / "verify" / "test_media.py").write_text("y", encoding="utf-8")
    assert ask(repo, decider, tmp_path)["Needed"] is True


# --------------------------------------------- and skipped when it is not

def test_the_dashboard_does_not_buy_it(repo, decider, tmp_path):
    """The point of the whole change. Nothing outside the pipeline can move
    where a kill is found or where a shot lands."""
    (repo / "autostream" / "webui.py").write_text("y", encoding="utf-8")
    got = ask(repo, decider, tmp_path)
    assert got["Needed"] is False
    assert "v1.0.0" in got["Why"]


def test_a_clean_tree_does_not_buy_it(repo, decider, tmp_path):
    assert ask(repo, decider, tmp_path)["Needed"] is False


def test_a_file_merely_NAMED_like_the_pipeline_does_not_buy_it(repo, decider,
                                                               tmp_path):
    """`autostream/clips_page.py` is not `autostream/clips/`. The rule is a
    path prefix and the trailing slash is load-bearing."""
    (repo / "autostream" / "clips_page.py").write_text("y", encoding="utf-8")
    assert ask(repo, decider, tmp_path)["Needed"] is False


def test_the_reason_is_always_said_out_loud(repo, decider, tmp_path):
    """A tier that silently stopped running is a tier nobody notices has
    stopped running."""
    (repo / "autostream" / "webui.py").write_text("y", encoding="utf-8")
    assert ask(repo, decider, tmp_path)["Why"].strip()


# ------------------------------------- every uncertain answer is "run it"

def test_no_tag_means_run_it(tmp_path, decider):
    r = tmp_path / "untagged"
    (r / "autostream").mkdir(parents=True)
    (r / "autostream" / "webui.py").write_text("x", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "first")
    got = ask(r, decider, tmp_path)
    assert got["Needed"] is True
    assert "tag" in got["Why"]


def test_not_a_checkout_at_all_means_run_it(tmp_path, decider):
    loose = tmp_path / "loose"
    loose.mkdir()
    got = ask(loose, decider, tmp_path)
    assert got["Needed"] is True


# ------------------------------------------------- the script still works

def test_the_gate_is_wired_into_the_script():
    src = VERIFY.read_text(encoding="utf-8-sig")
    assert "Test-MediaNeeded" in src
    # Called, not merely defined.
    assert src.count("Test-MediaNeeded") >= 2


def test_both_overrides_exist_and_the_build_passes_them_on():
    src = VERIFY.read_text(encoding="utf-8-sig")
    assert "[switch]$Media," in src
    assert "[switch]$NoMedia," in src
    build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8-sig")
    assert '$vargs += "-Media"' in build
    assert '$vargs += "-NoMedia"' in build


def test_forcing_it_on_beats_forcing_it_off():
    """-Media is somebody saying they know something a file list cannot.
    Given both, the safe one has to win."""
    src = VERIFY.read_text(encoding="utf-8-sig")
    assert "elseif ($NoMedia -and -not $Media) {" in src


def test_both_scripts_still_parse():
    """A PowerShell syntax error in the gate would surface as a release
    build that refuses to start, hours after the edit."""
    for script in (VERIFY, ROOT / "scripts" / "build.ps1"):
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$e=$null; $null=[System.Management.Automation.Language.Parser]"
             f"::ParseFile('{script}', [ref]$null, [ref]$e); "
             "if ($e) {{ $e | Out-String; exit 1 }}"],
            capture_output=True, text=True, timeout=120,
            creationflags=NO_WINDOW)
        assert out.returncode == 0, f"{script.name}: {out.stdout}{out.stderr}"
