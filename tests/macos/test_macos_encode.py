"""VideoToolbox: chosen on a Mac, never consulted on Windows, and a failure
costs a clip its speed rather than the clip."""
from __future__ import annotations

import sys

import pytest

from autostream.clips import tools
from autostream.macos import encode


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    encode.forget()
    monkeypatch.setattr(tools, "_HW_ENCODE_FAILED", False)
    monkeypatch.setattr(tools, "_SOFT", {})
    yield
    monkeypatch.undo()          # the real cached functions back, then clear them
    encode.forget()


def test_quality_maps_crf_onto_videotoolbox_scale():
    assert encode._quality(20) == 65
    assert encode._quality(18) > encode._quality(23)
    assert 1 <= encode._quality(0) <= 100 and 1 <= encode._quality(60) <= 100


def test_apple_silicon_gets_constant_quality(monkeypatch):
    monkeypatch.setattr(tools, "_encoders", lambda: "h264_videotoolbox")
    monkeypatch.setattr(encode, "_probe", lambda args: "-q:v" in args)
    assert encode._mode() == "quality"
    assert encode.args(20)[:2] == ["-c:v", "h264_videotoolbox"]
    assert "-q:v" in encode.args(20)


def test_an_intel_mac_falls_back_to_a_bitrate(monkeypatch):
    """Intel VideoToolbox refuses -q:v; the bitrate form is probed next."""
    monkeypatch.setattr(tools, "_encoders", lambda: "h264_videotoolbox")
    monkeypatch.setattr(encode, "_probe", lambda args: "-b:v" in args)
    assert encode._mode() == "bitrate"
    assert "-b:v" in encode.args(20)


def test_no_encoder_listed_means_none_is_probed(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "_encoders", lambda: "libx264")
    monkeypatch.setattr(encode, "_probe", lambda args: calls.append(args) or True)
    assert encode.available() is False and not calls


def test_auto_picks_videotoolbox_on_a_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(encode, "_mode", lambda: "quality")
    assert tools.gpu_encoder() == "videotoolbox"
    got = tools.video_codec_args("auto", cq=20)
    assert got[1] == "h264_videotoolbox"
    # ...and registered, so a failed encode is swapped for libx264.
    argv = ["-i", "x.mp4", *got, "out.mp4"]
    soft = tools.software_fallback(argv)
    assert soft is not None and "libx264" in soft and "h264_videotoolbox" not in soft


def test_cpu_is_still_cpu_on_a_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(encode, "_mode", lambda: "quality")
    assert tools.video_codec_args("libx264")[1] == "libx264"


def test_windows_never_asks_videotoolbox(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    for name in ("has_nvenc", "has_amf", "has_qsv"):
        monkeypatch.setattr(tools, name, lambda: False)

    def boom():
        raise AssertionError("Windows consulted the Mac encoder")

    monkeypatch.setattr(encode, "_mode", boom)
    monkeypatch.setattr(encode, "available", boom)
    assert tools.gpu_encoder() == ""
    assert tools.video_codec_args("auto")[1] == "libx264"


def test_a_mac_decodes_on_the_cpu_whatever_the_codec(monkeypatch):
    """-hwaccel videotoolbox made ffmpeg choose its hardware-only AV1 decoder,
    which on an M1 or M2 decodes nothing: zero frames, zero kills (#210)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert encode.decoder() == ""
    assert tools.hw_decoder() == ""
    assert tools.decode_args() == [] and tools.gpu_frames_args() == []
