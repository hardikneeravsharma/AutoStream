"""A GPU path is only taken on a machine that can run it -- and every vendor's is.

The usual Windows ffmpeg builds list `cuda` and `h264_nvenc` everywhere, card
or not. Taking that list at its word sent `-hwaccel cuda` to a friend's AMD
RX 9070 XT: ffmpeg exited 255 on every frame grab, the CS2 tally saw "0
samples", the calibrator showed six empty frames and the job failed blaming
the HUD colour. These pin the rule that fixed it: listed AND proven by a run.

Then the other half: with NVIDIA's paths correctly refused, that same Radeon
did everything on the CPU -- a 50-minute recording took 20 minutes with every
core pinned, though its ffmpeg had h264_amf and d3d11va all along. So an AMD
card decodes through D3D11VA and encodes through AMF, an Intel one through
D3D11VA and Quick Sync, and NVIDIA keeps CUDA and NVENC.

No ffmpeg is needed -- subprocess is faked, so this runs on any machine.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from autostream.clips import tools

# What each kind of card can actually run, of what Gyan's build lists.
RUNS = {
    "nvidia": {"cuda", "h264_nvenc", "d3d11va"},
    "amd": {"h264_amf", "d3d11va"},
    "intel": {"h264_qsv", "d3d11va"},
    None: set(),
}
CACHED = ("has_cuda", "has_nvenc", "has_amf", "has_qsv", "has_d3d11va", "_encoders", "_tiny_h264")


def _clear():
    for name in CACHED:
        getattr(tools, name).cache_clear()


@pytest.fixture
def ffmpeg(monkeypatch):
    """A fake ffmpeg that lists every vendor's paths, and whose GPU runs succeed
    only for the paths `card` can run -- what Gyan's build does on each machine."""
    state = SimpleNamespace(card=None, listed=True, calls=[], amf_on_other_card=False)

    def fake_run(args, **kw):
        state.calls.append(args)
        if "-hwaccels" in args:
            out = "Hardware acceleration methods:\ncuda\nd3d11va\nqsv\namf\n" if state.listed \
                else "Hardware acceleration methods:\ndxva2\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "-encoders" in args:
            out = (" V....D h264_nvenc   NVIDIA NVENC H.264 encoder\n"
                   " V....D h264_amf     AMD AMF H.264 Encoder\n"
                   " V..... h264_qsv     H.264 (Intel Quick Sync Video acceleration)\n") if state.listed \
                else " V....D libx264   libx264 H.264\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        # The probe itself: the step that needs a real card.
        joined = " ".join(args)
        if "libx264" in joined:                                   # the sample file
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if "-hwaccel" in args and "h264_amf" in args and state.amf_on_other_card:
            return SimpleNamespace(returncode=1, stdout=b"",
                                   stderr=b"Failed to create derived AMF device")
        wants = next((w for w in ("h264_nvenc", "h264_amf", "h264_qsv") if w in joined), None) \
            or next((w for w in ("cuda", "d3d11va") if f"{w}=gpu" in joined), None)
        ok = wants in RUNS[state.card]
        return SimpleNamespace(returncode=0 if ok else 255, stdout=b"", stderr=b"no such device")

    monkeypatch.setattr(tools, "binary", lambda name: name)
    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    monkeypatch.setattr(tools, "_HW_ENCODE_FAILED", False)
    _clear()
    yield state
    _clear()


def test_a_listed_cuda_without_a_card_is_not_used(ffmpeg):
    assert tools.has_cuda() is False


def test_a_listed_nvenc_without_a_card_is_not_used(ffmpeg):
    assert tools.has_nvenc() is False


def test_without_a_card_clips_encode_and_decode_in_software(ffmpeg):
    """The cut and the reel: a hardware encoder that is not there fails the render outright."""
    assert tools.video_codec_args()[:2] == ["-c:v", "libx264"]
    assert tools.decode_args() == [] and tools.gpu_frames_args() == []


def test_with_an_nvidia_card_cuda_and_nvenc_are_used(ffmpeg):
    ffmpeg.card = "nvidia"
    assert tools.has_cuda() is True
    assert tools.has_nvenc() is True
    assert tools.video_codec_args()[:2] == ["-c:v", "h264_nvenc"]
    assert tools.decode_args() == ["-hwaccel", "cuda"]
    assert tools.gpu_frames_args() == ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]


def test_an_amd_card_decodes_through_d3d11va_and_encodes_through_amf(ffmpeg):
    """The friend's RX 9070 XT: everything on the CPU, though its ffmpeg had both."""
    ffmpeg.card = "amd"
    assert tools.has_cuda() is False and tools.has_nvenc() is False
    assert tools.gpu_encoder() == "amf"
    args = tools.video_codec_args(cq=19)
    assert args[:2] == ["-c:v", "h264_amf"]
    assert args[args.index("-qp_i") + 1] == "19"
    assert tools.decode_args() == ["-hwaccel", "d3d11va"]
    assert tools.gpu_frames_args() == ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"]


def test_an_intel_card_encodes_through_quick_sync(ffmpeg):
    ffmpeg.card = "intel"
    assert tools.gpu_encoder() == "qsv"
    assert tools.video_codec_args()[:2] == ["-c:v", "h264_qsv"]
    assert tools.decode_args() == ["-hwaccel", "d3d11va"]


def test_a_named_encoder_the_machine_cannot_run_falls_back_to_the_cpu(ffmpeg):
    ffmpeg.card = "amd"
    assert tools.video_codec_args("nvenc")[:2] == ["-c:v", "libx264"]
    assert tools.video_codec_args("amf")[:2] == ["-c:v", "h264_amf"]


def test_a_build_without_them_is_not_probed(ffmpeg):
    """Nothing to try, so nothing is run beyond the listing."""
    ffmpeg.listed = False
    ffmpeg.card = "nvidia"
    assert tools.has_cuda() is False
    assert tools.has_nvenc() is False
    assert tools.decode_args() == []
    assert tools.gpu_encoder() == ""
    assert not any("-init_hw_device" in a or any(str(x).startswith("h264_") for x in a)
                   for a in ffmpeg.calls)


def test_the_answer_is_asked_once(ffmpeg):
    """Thirteen callers ask; a probe per frame grab would cost a second each."""
    ffmpeg.card = "amd"
    for _ in range(5):
        tools.has_cuda()
        tools.decode_args()
        tools.video_codec_args()
    assert sum("-init_hw_device" in a for a in ffmpeg.calls) == 2      # cuda, then d3d11va
    assert sum("h264_amf" in a for a in ffmpeg.calls) == 2         # alone, then behind d3d11va


def test_a_probe_that_hangs_counts_as_no_card(ffmpeg, monkeypatch):
    def hang(args, **kw):
        if "-hwaccels" in args:
            return SimpleNamespace(returncode=0, stdout="cuda\nd3d11va\n", stderr="")
        raise subprocess.TimeoutExpired(args, kw.get("timeout") or 0)

    monkeypatch.setattr(tools.subprocess, "run", hang)
    assert tools.has_cuda() is False
    assert tools.decode_args() == []


def test_a_hardware_encode_that_fails_is_run_again_on_the_cpu_and_never_asked_again(ffmpeg, monkeypatch):
    """The AMF path cannot be run on the machine it was written on: a failure
    must cost the clip its speed, not the clip."""
    ffmpeg.card = "amd"
    monkeypatch.setattr(tools, "_HW_ENCODE_FAILED", False)
    monkeypatch.setattr(tools, "_SOFT", {})
    hw = tools.video_codec_args(cq=21)
    assert hw[1] == "h264_amf"
    tries = []

    def fake_run(args, **kw):
        tries.append(args)
        if "h264_amf" in args:
            raise RuntimeError("ffmpeg failed (1):\n[h264_amf] encode session failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(tools, "run", fake_run)
    tools.ffmpeg("-i", "in.mp4", *hw, "out.mp4")
    assert len(tries) == 2 and "libx264" in tries[1] and "-crf" in tries[1]
    assert tries[1][tries[1].index("-crf") + 1] == "21"
    assert tools.video_codec_args()[1] == "libx264"           # the rest of the run
    assert tools.gpu_encoder() == ""


def test_a_failure_with_no_hardware_encoder_in_it_is_not_retried(ffmpeg, monkeypatch):
    monkeypatch.setattr(tools, "_SOFT", {})

    def fail(args, **kw):
        raise RuntimeError("ffmpeg failed (1):\nNo such file")
    monkeypatch.setattr(tools, "run", fail)
    with pytest.raises(RuntimeError):
        tools.ffmpeg("-i", "missing.mp4", "-c:v", "libx264", "out.mp4")


def test_amf_is_not_used_behind_another_vendors_decoder(ffmpeg):
    """An NVIDIA-less box whose display card is not the Radeon: AMF alone encodes,
    but behind a D3D11VA decode it cannot build its device. Measured: exit 1,
    "Failed to create derived AMF device". The decode stays on the card."""
    ffmpeg.card = "amd"
    ffmpeg.amf_on_other_card = True
    assert tools.has_amf() is False
    assert tools.video_codec_args()[1] == "libx264"
    assert tools.decode_args() == ["-hwaccel", "d3d11va"]
