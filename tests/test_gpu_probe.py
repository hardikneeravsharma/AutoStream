"""An NVIDIA path is only taken on a machine that can run it.

The usual Windows ffmpeg builds list `cuda` and `h264_nvenc` everywhere, card
or not. Taking that list at its word sent `-hwaccel cuda` to a friend's AMD
RX 9070 XT: ffmpeg exited 255 on every frame grab, the CS2 tally saw "0
samples", the calibrator showed six empty frames and the job failed blaming
the HUD colour. These pin the rule that fixed it: listed AND proven by a run.

No ffmpeg is needed -- subprocess is faked, so this runs on any machine.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from autostream.clips import tools


@pytest.fixture
def ffmpeg(monkeypatch):
    """A fake ffmpeg that lists both NVIDIA paths, and whose GPU runs succeed
    only when `card` is set -- what Gyan's build does on each kind of machine."""
    state = SimpleNamespace(card=False, listed=True, calls=[])

    def fake_run(args, **kw):
        state.calls.append(args)
        if "-hwaccels" in args:
            out = "Hardware acceleration methods:\ncuda\nd3d11va\n" if state.listed \
                else "Hardware acceleration methods:\nd3d11va\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "-encoders" in args:
            out = " V....D h264_nvenc   NVIDIA NVENC H.264 encoder\n" if state.listed \
                else " V....D libx264   libx264 H.264\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        # The probe itself: the step that needs a real card.
        return SimpleNamespace(returncode=0 if state.card else 255,
                               stdout=b"", stderr=b"Cannot load nvcuda.dll")

    monkeypatch.setattr(tools, "binary", lambda name: name)
    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    tools.has_cuda.cache_clear()
    tools.has_nvenc.cache_clear()
    yield state
    tools.has_cuda.cache_clear()
    tools.has_nvenc.cache_clear()


def test_a_listed_cuda_without_a_card_is_not_used(ffmpeg):
    assert tools.has_cuda() is False


def test_a_listed_nvenc_without_a_card_is_not_used(ffmpeg):
    assert tools.has_nvenc() is False


def test_without_a_card_clips_encode_in_software(ffmpeg):
    """The cut and the reel: NVENC on a Radeon fails the render outright."""
    assert tools.video_codec_args()[:2] == ["-c:v", "libx264"]


def test_with_a_card_both_are_used(ffmpeg):
    ffmpeg.card = True
    assert tools.has_cuda() is True
    assert tools.has_nvenc() is True
    assert tools.video_codec_args()[:2] == ["-c:v", "h264_nvenc"]


def test_a_build_without_them_is_not_probed(ffmpeg):
    """Nothing to try, so nothing is run beyond the listing."""
    ffmpeg.listed = False
    ffmpeg.card = True
    assert tools.has_cuda() is False
    assert tools.has_nvenc() is False
    assert not any("-init_hw_device" in a or "h264_nvenc" in a
                   for a in ffmpeg.calls)


def test_the_answer_is_asked_once(ffmpeg):
    """Thirteen callers ask; a probe per frame grab would cost a second each."""
    for _ in range(5):
        tools.has_cuda()
    assert sum("-init_hw_device" in a for a in ffmpeg.calls) == 1


def test_a_probe_that_hangs_counts_as_no_card(ffmpeg, monkeypatch):
    def hang(args, **kw):
        if "-hwaccels" in args:
            return SimpleNamespace(returncode=0, stdout="cuda\n", stderr="")
        raise subprocess.TimeoutExpired(args, kw.get("timeout") or 0)

    monkeypatch.setattr(tools.subprocess, "run", hang)
    assert tools.has_cuda() is False
