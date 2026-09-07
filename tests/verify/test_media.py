"""The clip detectors, measured against footage a person has looked at.

Tier 4. Marked `media`, so it is excluded from a plain `pytest -q` and runs
only when the corpus exists -- see tests/verify/corpus.py.

This is the tier CLAUDE.md has been asking for and the repo has never had.
Every other test of the detectors runs against frames the test drew itself,
in the colours and at the geometry the detector expects. That proves the
arithmetic and cannot prove the thing that actually goes wrong, which is a
detector meeting real footage and reading it differently than a person does.

THE DETECTOR IS CALLED DIRECTLY. detect.scan, never POST /api/clips/run. Going
through the API would hand the measurement to webui._cached_kills, which reuses
the kill list from an earlier run of the same recording -- so a fixed detector
would be scored on the output of the detector before the fix. That trap is
documented in CLAUDE.md and it is live in the shipped UI.

TRUTH IS REVIEWED, NEVER INFERRED. The baselines are what a person confirmed
while watching the excerpt, plus what they said was missed. Seeding them from
the detector's own output would make every one of these tests a tautology.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import score
from autostream.clips import detect, profiles

pytestmark = pytest.mark.media

CORPUS = Path(os.environ.get("AUTOSTREAM_TESTDATA", r"C:\autostream-testdata"))


def _manifest() -> list[dict]:
    p = CORPUS / "manifest.json"
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8"))["excerpts"]


MANIFEST = _manifest()

# Only excerpts somebody has reviewed can be asserted on. The rest are
# reported by test_the_whole_corpus_has_been_reviewed rather than skipped
# quietly, so a half-reviewed corpus is visible instead of looking complete.
REVIEWED = [
    e for e in MANIFEST
    if (score.baseline(e["game"]).get("clips") or {}).get(e["clip"])
]


def _id(e: dict) -> str:
    return e["clip"]


def _names() -> dict[str, str]:
    """In-game names for the profiles that need one, from BESIDE THE CORPUS.

    A kill-feed profile cannot be measured without the name it looks for, and
    that name is personal data. It used to arrive from the tracked
    config/games.yaml -- which meant one person's handle sat in a public repo
    and seeded every install, so it was removed. This tier then silently began
    SKIPPING Counter-Strike rather than measuring it, which is the worse
    failure of the two: a tier that measures nothing still reports success.

    So the name lives next to the corpus, which is already private,
    machine-specific and never committed. Absent, the tier skips exactly as it
    would have anyway, and says where to put it.
    """
    p = CORPUS / "names.json"
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): str(v) for k, v in (raw or {}).items() if v}


def _prof(game_key: str):
    """The profile, with a name filled in from beside the corpus if it needs one.

    dataclasses.replace, never profiles.remember: running the tier must not
    write anybody's name into the config as a side effect.
    """
    import dataclasses

    prof = profiles.for_game(game_key)
    if prof is None:
        return None
    name = _names().get(game_key.lower())
    if name and not prof.player:
        prof = dataclasses.replace(prof, player=name)
    return prof


@pytest.fixture(scope="session")
def scanned() -> dict:
    """Every reviewed excerpt, scanned once, by the detector as it is now.

    Session-scoped because a scan is seconds of real decoding and four tests
    ask about each result. Not read from detections.json: that file is the
    OUTPUT of whatever the detector was when it was written, and reusing it
    would mean this tier never actually ran the code it claims to test.
    """
    out: dict[str, list[float]] = {}
    for e in REVIEWED:
        prof = _prof(e["game_key"])
        assert prof is not None, f"no profile for {e['game_key']}"
        missing = prof.missing()
        if missing:
            pytest.skip(
                f"{e['game_key']} is not set up on this machine: "
                f"{[m['key'] for m in missing]}. An in-game name belongs in "
                f"{CORPUS / 'names.json'}, as "
                f'{{"{e["game_key"]}": "YourName"}} -- never in the repo, '
                f"which is public.")
        kills = detect.scan(CORPUS / e["file"], prof)
        out[e["clip"]] = [round(float(k.time), 2) for k in kills]
    return out


def _score(e: dict, scanned: dict) -> tuple[dict, dict, dict]:
    base = score.baseline(e["game"])["clips"][e["clip"]]
    prof = _prof(e["game_key"])
    tol = base.get("tolerance") or score.TOLERANCE.get(prof.mode, 2.0)
    m = score.match(scanned[e["clip"]], base.get("truth", []), tol)
    return base, m, score.metrics(m)


# ---------------------------------------------------------------- corpus

def test_there_is_a_corpus_to_measure_against():
    assert MANIFEST, (
        f"no corpus at {CORPUS}. Build one:\n"
        "  .venv\\Scripts\\python.exe tests\\verify\\corpus.py build")


def test_every_excerpt_named_in_the_manifest_is_actually_there():
    """A manifest that outlives its files would make this tier pass by
    scanning nothing."""
    gone = [e["clip"] for e in MANIFEST if not (CORPUS / e["file"]).is_file()]
    assert gone == [], f"in the manifest but not on disk: {gone}"


def test_all_three_games_are_covered():
    """Delta Force is template matching, VALORANT is a colour border, CS2 is
    OCR. They fail in completely different ways; two of the three is not
    coverage of the clipper."""
    games = {e["game"] for e in MANIFEST}
    assert {"valorant", "cs2", "deltaforce"} <= games, f"only covers {games}"


def test_every_game_has_a_quiet_excerpt():
    """The half of the problem nothing else tests: a detector that fires on
    footage where nothing happened produces clips of nothing, and recall
    alone would score that perfect."""
    kinds: dict[str, set] = {}
    for e in MANIFEST:
        kinds.setdefault(e["game"], set()).add(e["kind"])
    without = sorted(g for g, k in kinds.items() if "quiet" not in k)
    assert without == [], f"no quiet excerpt for: {without}"


def test_the_whole_corpus_has_been_reviewed():
    """Until an excerpt is reviewed, nothing below can fail on it."""
    unreviewed = sorted(e["clip"] for e in MANIFEST if e not in REVIEWED)
    assert unreviewed == [], (
        "these excerpts have no reviewed baseline, so tier 4 cannot fail on "
        "them. Review them (review.py build) and import the verdicts: "
        + str(unreviewed))


# ------------------------------------------------------------ the scores

@pytest.mark.parametrize("e", REVIEWED, ids=_id)
def test_the_detector_still_finds_what_a_person_confirmed(e, scanned):
    """Recall. A miss is a highlight that never got cut."""
    base, m, got = _score(e, scanned)
    floor = base.get("floor", {}).get("recall", 0.85)
    assert got["recall"] >= floor, (
        f"{e['clip']}: recall {got['recall']:.2f} is below its floor {floor:.2f}. "
        f"Missed {len(m['missed'])} of {got['tp'] + got['fn']} confirmed kills, "
        f"at {[round(t, 1) for t in m['missed']]}")


@pytest.mark.parametrize("e", REVIEWED, ids=_id)
def test_the_detector_does_not_invent_kills(e, scanned):
    """Precision. Each false positive is a clip of nothing that a viewer
    actually watches, which is the failure they notice first."""
    base, m, got = _score(e, scanned)
    floor = base.get("floor", {}).get("precision", 0.95)
    assert got["precision"] >= floor, (
        f"{e['clip']}: precision {got['precision']:.2f} is below its floor "
        f"{floor:.2f}. Reported {len(m['extra'])} kill(s) that are not there, "
        f"at {[round(t, 1) for t in m['extra']]}")


@pytest.mark.parametrize(
    "e", [e for e in REVIEWED if e["kind"] == "quiet"], ids=_id)
def test_a_quiet_excerpt_does_not_get_noisier(e, scanned):
    """Counted, not scored. On an excerpt with no confirmed kills, precision
    is 0 for one false positive and 0 for twenty, so the count is the only
    thing that says whether it drifted or fell apart.

    Delta Force reports three here today, on 182 seconds a person confirmed
    has no kills in it. That is recorded as the ceiling rather than asserted
    away: the number must not grow, and getting it to zero is a fix.
    """
    base = score.baseline(e["game"])["clips"][e["clip"]]
    if base.get("truth"):
        pytest.skip("review found real kills here, so it is not a quiet excerpt")
    ceiling = base.get("floor", {}).get("max_false_positives", 0)
    found = scanned[e["clip"]]
    assert len(found) <= ceiling, (
        f"{e['clip']} is {e.get('seconds', 0):.0f}s a person confirmed has no "
        f"kills in it. The detector reported {len(found)}, up from {ceiling}: "
        f"{[round(t, 1) for t in found]}")


@pytest.mark.parametrize("game", ["valorant", "cs2", "deltaforce"])
def test_the_game_as_a_whole_does_not_regress(game, scanned):
    """Per-excerpt floors can each be met while the game is worse overall --
    one excerpt carrying four that scraped through. This is the aggregate,
    against what the detector scored on the day the baseline was reviewed.
    """
    rows = [e for e in REVIEWED if e["game"] == game]
    if not rows:
        pytest.skip(f"no reviewed {game} excerpts")
    base = score.baseline(game)
    tp = fn = fp = 0
    for e in rows:
        _, _, got = _score(e, scanned)
        tp, fn, fp = tp + got["tp"], fn + got["fn"], fp + got["fp"]
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    floor = base.get("floor", {})
    assert recall >= floor.get("recall", 0.0), (
        f"{game}: recall fell to {recall:.2f} from {floor.get('recall'):.2f} "
        f"across {len(rows)} excerpts ({fn} missed of {tp + fn})")
    assert precision >= floor.get("precision", 0.0), (
        f"{game}: precision fell to {precision:.2f} from "
        f"{floor.get('precision'):.2f} across {len(rows)} excerpts "
        f"({fp} invented)")


@pytest.mark.parametrize("game", ["valorant", "cs2", "deltaforce"])
def test_the_gap_to_target_is_recorded_and_visible(game):
    """Not a pass/fail on quality -- a statement of where each detector is.

    The floors above stop things sliding backwards. They deliberately do not
    demand `target`, because two of the three do not meet it: on the reviewed
    corpus VALORANT finds 45% of kills and CS2 finds 75%. Wiring the gate to
    the target would fail every build from the day it was switched on, and a
    gate that always fails gets switched off. This keeps the number in front
    of whoever reads the output instead.
    """
    base = score.baseline(game)
    if not base:
        pytest.skip(f"no baseline for {game}")
    m, target = base.get("measured", {}), base.get("target", {})
    assert m, f"{game} baseline has no measured block; re-import it"
    short = [f"{k} {m[k]:.2f} vs target {target[k]:.2f}"
             for k in ("recall", "precision")
             if k in target and m.get(k, 0) < target[k]]
    if short:
        print(f"\n  {game}: {'; '.join(short)}")


# ------------------------------------------------- the template, directly

VODCLIPPER = Path(r"C:\vodclipper\calib")


@pytest.mark.parametrize("frame", sorted(VODCLIPPER.glob("full_*.png"))
                         if VODCLIPPER.is_dir() else [])
def test_the_delta_force_template_stays_quiet_on_a_frame_with_no_marker(frame):
    """Six real 720p frames with no kill in them, scored in milliseconds.

    These were kept from the prototype this detector grew out of. They were
    assumed to be frames captured AT kills -- they are not: measured against
    that run's own kills.json, not one of them has a kill within six seconds.
    They are frames from hunting for where the skull sits on screen, which is
    why the file beside them is called skull_hunt.png.

    That makes them worth more than the positives they were mistaken for.
    Real gameplay with no marker is exactly where a false positive comes from,
    and this runs without decoding a single video. Positives are covered by
    the corpus, against footage a person has confirmed.
    """
    np = pytest.importorskip("numpy")
    from PIL import Image

    prof = profiles.for_game("deltaforceclient.exe")
    assert prof is not None
    tmpl0 = detect.load_template(prof)
    assert tmpl0 is not None, "the Delta Force template is gone"

    # Exactly what scan_span does, and for the same reason it does it: crop at
    # native resolution so nothing is resampled twice, then bring the BAND to
    # the geometry the template was cut at. Scaling the template instead reads
    # as an honest mistake and is not -- it scored these frames at 0.34 against
    # a floor of 0.75 and looked like a broken detector.
    a = np.asarray(Image.open(frame).convert("L"))
    h, w = a.shape
    (x, y, bw, bh), (rw, rh) = detect.band_geometry(w, h, prof)
    band = Image.fromarray(a[y:y + bh, x:x + bw]).resize((rw, rh), Image.BILINEAR)
    band = np.asarray(band, dtype=np.float32)
    if band.shape[0] < tmpl0.shape[0] or band.shape[1] < tmpl0.shape[1]:
        pytest.skip(f"{frame.name}: band {band.shape} smaller than the template")

    got, count = detect.ncc(band, tmpl0, prof.match_min)
    assert count == 0 and got < prof.match_min, (
        f"{frame.name}: scored {got:.3f} against match_min {prof.match_min} "
        f"with {count} hit(s), on a frame that has no kill in it. Lowering "
        f"match_min buys recall and pays for it here first.")
