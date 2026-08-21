r"""Configure OBS local recording for clip production, over the websocket.

WHY THIS EXISTS
    Clips cut from the YouTube VOD are a copy of a copy: OBS sends 1080p60 at
    10 Mbps, YouTube re-encodes that to roughly 4.5 Mbps, and Studio hands back
    a 720p30 transcode of *that*. OBS can record to disk while streaming, from
    the same canvas, and that local file is the editing master.

WHAT IT CHANGES
    RecQuality  Small -> HQ        NVENC CQP ~23 -> ~16, i.e. visually lossless
    RecTracks   1     -> 7         bitmask, tracks 1|2|3
    Mic/Aux              tracks 1 and 2 only
    Desktop Audio        tracks 1 and 3 only
    Record directory  -> a dedicated folder, so nothing else gets mixed in

    Track 1 stays the full mix, which is what any player and the clipper pick
    up by default. Tracks 2 and 3 isolate the mic and the game so the balance
    can be fixed after the fact instead of being baked in at record time.

WHAT IT DELIBERATELY LEAVES ALONE
    RecEncoder=nvenc      H.264 is universally editable, and at CQP 16 the
                          quality gain from HEVC is not worth the compatibility
    RecFormat2=hybrid_mp4 already crash-resistant; mkv+remux buys nothing here
    Every streaming key   the stream is not the problem

WHY SIMPLE MODE AND NOT ADVANCED
    Advanced mode would allow recording the full 2560x1440 canvas rather than
    the downscaled 1080p output. It cannot be configured from here: profile
    parameters land in basic.ini, but encoder settings live in
    streamEncoder.json / recordEncoder.json inside the profile directory.
    Flipping Output.Mode to Advanced remotely would leave the *stream* encoder
    at its defaults (~2500 kbps) and quietly wreck the broadcast. Use the OBS
    GUI for that; --help prints the steps.

Run:  .venv\Scripts\python scripts\configure_recording.py
      .venv\Scripts\python scripts\configure_recording.py --dry-run
      .venv\Scripts\python scripts\configure_recording.py --revert
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autostream import cfg  # noqa: E402

# Track 1 = mix (what the clipper and every player use), 2 = mic, 3 = game.
MIC_TRACKS = {"1": True, "2": True, "3": False, "4": False, "5": False, "6": False}
DESKTOP_TRACKS = {"1": True, "2": False, "3": True, "4": False, "5": False, "6": False}
REC_TRACKS_MASK = "7"          # tracks 1|2|3
REC_QUALITY = "HQ"             # OBS calls this "Indistinguishable Quality"

DEFAULT_DIR = Path.home() / "Videos" / "AutoStream"

# The names OBS gives its two default audio inputs. A renamed source is matched
# by kind instead -- see _audio_inputs().
MIC_KINDS = {"wasapi_input_capture"}
DESKTOP_KINDS = {"wasapi_output_capture"}


# --------------------------------------------------------------------------- io

def connect():
    import obsws_python as obsws

    c = cfg.load()
    ob = c["obs"]
    return obsws.ReqClient(host=ob["host"], port=int(ob["port"]),
                           password=c.obs_password, timeout=8)


def gp(cl, category: str, name: str) -> str:
    try:
        return cl.get_profile_parameter(category, name).parameter_value
    except Exception as e:                                    # noqa: BLE001
        return f"<error: {e}>"


def _audio_inputs(cl) -> tuple[str | None, str | None]:
    """-> (mic input name, desktop input name), matched by kind not by label.

    Matching on the literal strings "Mic/Aux" and "Desktop Audio" breaks the
    moment anyone renames a source, and renaming them is the first thing most
    people do.
    """
    mic = desktop = None
    for inp in cl.get_input_list().inputs:
        kind = inp.get("inputKind", "")
        name = inp.get("inputName", "")
        if kind in MIC_KINDS and mic is None:
            mic = name
        elif kind in DESKTOP_KINDS and desktop is None:
            desktop = name
    return mic, desktop


def ffprobe_streams(path: Path) -> dict:
    """-> {audio: n, width, height, bitrate, duration} for a media file."""
    exe = shutil.which("ffprobe")
    if not exe:
        # winget puts ffmpeg under a versioned package directory and only adds
        # it to PATH for *new* shells, so PATH alone is not enough.
        import os
        pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        root = pkgs / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        hits = list(root.rglob("ffprobe.exe")) if root.exists() else []
        if not hits:
            return {}
        exe = str(hits[0])
    p = subprocess.run([exe, "-v", "quiet", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return {}
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    return {
        "audio": sum(1 for s in d["streams"] if s["codec_type"] == "audio"),
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "vcodec": v.get("codec_name", "?"),
        "bitrate": int(d["format"].get("bit_rate", 0)),
        "duration": float(d["format"].get("duration", 0.0)),
        "size": int(d["format"].get("size", 0)),
    }


# ------------------------------------------------------------------------ apply

def show(cl, header: str, mic: str | None, desktop: str | None) -> None:
    print(f"\n{header}")
    print(f"  Output.Mode                 {gp(cl, 'Output', 'Mode')}")
    for k in ("RecQuality", "RecEncoder", "RecFormat2", "RecTracks"):
        print(f"  SimpleOutput.{k:<15} {gp(cl, 'SimpleOutput', k)}")
    try:
        print(f"  Record directory            {cl.get_record_directory().record_directory}")
    except Exception as e:                                    # noqa: BLE001
        print(f"  Record directory            <error: {e}>")
    for label, name in (("mic", mic), ("desktop", desktop)):
        if not name:
            print(f"  {label:<10} tracks           <no such input>")
            continue
        try:
            t = cl.get_input_audio_tracks(name).input_audio_tracks
            on = ",".join(k for k in sorted(t) if t[k])
            print(f"  {label:<10} tracks           {name!r} -> {on or 'none'}")
        except Exception as e:                                # noqa: BLE001
            print(f"  {label:<10} tracks           <error: {e}>")


def apply(cl, directory: Path, mic: str | None, desktop: str | None,
          *, revert: bool) -> None:
    quality = "Small" if revert else REC_QUALITY
    mask = "1" if revert else REC_TRACKS_MASK

    cl.set_profile_parameter("SimpleOutput", "RecQuality", quality)
    cl.set_profile_parameter("SimpleOutput", "RecTracks", mask)

    if not revert:
        directory.mkdir(parents=True, exist_ok=True)
        cl.set_record_directory(str(directory))

    # Both inputs ship enabled on all six tracks, so without this a 3-track
    # recording would just be the same mix three times over.
    all_on = {str(i): True for i in range(1, 7)}
    if mic:
        cl.set_input_audio_tracks(mic, all_on if revert else dict(MIC_TRACKS))
    if desktop:
        cl.set_input_audio_tracks(desktop, all_on if revert else dict(DESKTOP_TRACKS))


# ----------------------------------------------------------------------- verify

def verify(cl, expect_tracks: int) -> bool:
    """Record for 5 seconds and ffprobe the result.

    The writes are not trusted on their own. RecTracks in particular is being
    set as a BITMASK, and the previous value of 1 is ambiguous -- it reads the
    same whether OBS wants a mask or a track index. Only the file settles it.
    """
    print("\nverifying with a 5-second test recording...")
    if cl.get_record_status().output_active:
        print("  SKIPPED - OBS is already recording. Stop it and re-run.")
        return False

    cl.start_record()
    time.sleep(5)
    out = cl.stop_record().output_path
    if not out:
        print("  FAILED - OBS did not report an output path")
        return False

    path = Path(out)
    # hybrid_mp4 finalises the moov atom after the output closes; give it a beat.
    for _ in range(20):
        if path.exists() and path.stat().st_size > 0:
            break
        time.sleep(0.25)

    info = ffprobe_streams(path)
    if not info:
        print(f"  wrote {path}")
        print("  ffprobe unavailable - inspect the file by hand")
        return False

    mbps = info["bitrate"] / 1_000_000
    print(f"  file        {path.name}  ({info['size']/1024/1024:.1f} MB, "
          f"{info['duration']:.1f}s)")
    print(f"  video       {info['width']}x{info['height']} {info['vcodec']}")
    # Deliberately NOT extrapolated to GB/hour. CQP is quality-targeted, so an
    # idle desktop encodes to near nothing while 1080p60 gameplay lands around
    # 40-60 Mbps. A five-second capture of a static scene would understate the
    # real cost by two orders of magnitude.
    print(f"  bitrate     {mbps:.1f} Mbps on this static test scene")
    print(f"              (gameplay at CQP 16 runs ~40-60 Mbps, ~20-30 GB/hour)")
    print(f"  audio       {info['audio']} track(s), expected {expect_tracks}")

    ok = info["audio"] == expect_tracks
    if not ok:
        print("\n  TRACKS DID NOT TAKE. SimpleOutput.RecTracks is probably not a")
        print("  bitmask on this build. Set the recording audio tracks by hand:")
        print("  OBS > Settings > Output > Recording > Audio Track: tick 1, 2, 3")

    # OBS keeps the handle open briefly after the output closes while it
    # finalises the container, so a straight unlink races it and raises
    # WinError 32.
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            print("  removed the test file")
            break
        except PermissionError:
            time.sleep(0.25)
    else:
        print(f"  could not remove the test file - delete it by hand: {path}")
    return ok


GUI_STEPS = """
Recording the full 2560x1440 canvas (optional, manual)
------------------------------------------------------
Simple mode records at the OUTPUT resolution, so today that is 1080p. Cropping
1080p to 9:16 gives 607x1080 and needs a 1.78x upscale to reach 1080x1920;
from 1440p you get 810x1440 and only need 1.33x. It is a real gain for vertical
clips, and it cannot be done safely over the websocket.

  1. OBS > Settings > Output > Output Mode: Advanced
  2. Streaming tab - confirm it still reads: Encoder NVIDIA NVENC H.264,
     Rate Control CBR, Bitrate 10000 Kbps. If it does not, set it. This is the
     step that matters; the defaults are much lower.
  3. Recording tab:
       Type              Standard
       Recording Path    the folder this script configured
       Format            hybrid MP4
       Audio Track       1, 2, 3
       Encoder           NVIDIA NVENC H.264
       Rescale Output    off  (leave it off - off means full canvas)
       Rate Control      CQP,  CQ Level 16
  4. Apply, then stream for a minute and check both outputs.
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Configure OBS local recording for clip production.",
        epilog=GUI_STEPS, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                    help=f"recording folder (default: {DEFAULT_DIR})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print current settings and exit")
    ap.add_argument("--revert", action="store_true",
                    help="restore RecQuality=Small, one audio track")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the 5-second test recording")
    a = ap.parse_args()

    try:
        cl = connect()
    except Exception as e:                                    # noqa: BLE001
        print(f"could not reach obs-websocket: {e}")
        print("Is OBS running, with Tools > WebSocket Server Settings enabled?")
        return 1

    mic, desktop = _audio_inputs(cl)
    if not mic:
        print("warning: no microphone input found (wasapi_input_capture)")
    if not desktop:
        print("warning: no desktop audio input found (wasapi_output_capture)")

    show(cl, "BEFORE", mic, desktop)
    if a.dry_run:
        print("\n--dry-run: nothing changed.")
        return 0

    apply(cl, a.dir, mic, desktop, revert=a.revert)
    show(cl, "AFTER", mic, desktop)

    ok = True
    if not a.no_verify:
        ok = verify(cl, expect_tracks=1 if a.revert else 3)

    if a.revert:
        print("\nReverted.")
    else:
        print("\nDone. OBS picks the new settings up on the next recording start;")
        print("the Settings dialog will show them once reopened.")
        print(GUI_STEPS)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
