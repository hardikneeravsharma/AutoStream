"""Heavy extras downloaded at the user's asking (autostream/packs.py).

The player (2026-11-02): when a feature's heavy libraries or models are not on
the machine, ask and download them. These prove the parts that decide what is
downloaded and where it goes -- with PyPI and the network faked, as the suite
never touches either.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from autostream import packs, paths, webui


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PACKS_DIR", tmp_path / "packs")
    return tmp_path


@pytest.mark.parametrize("name, rank", [
    ("ctranslate2-4.8.4-cp312-cp312-win_amd64.whl", 0),
    ("tokenizers-0.23.3-cp310-abi3-win_amd64.whl", 1),
    ("hf_xet-1.8.0-cp38-abi3-win_amd64.whl", 1),
    ("nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl", 2),
    ("faster_whisper-1.2.1-py3-none-any.whl", 3),
    ("colorama-0.4.6-py2.py3-none-any.whl", 3),
    ("ctranslate2-4.8.4-cp311-cp311-win_amd64.whl", None),     # another Python
    ("tokenizers-0.23.3-cp314-cp314t-win_amd64.whl", None),
    ("tokenizers-0.23.3-cp310-abi3-win_arm64.whl", None),       # another machine
    ("av-19.0.2-cp312-abi3-macosx_11_0_arm64.whl", None),
])
def test_which_wheels_this_app_can_load(name, rank, monkeypatch):
    monkeypatch.setattr(packs, "PY", "cp312")
    assert packs._rank(name) == rank


def test_the_best_fitting_wheel_is_chosen(monkeypatch):
    monkeypatch.setattr(packs, "PY", "cp312")
    files = [{"filename": "x-1-py3-none-any.whl"}, {"filename": "x-1-cp312-cp312-win_amd64.whl"},
             {"filename": "x-1.tar.gz"}, {"filename": "x-1-cp312-cp312-win32.whl"}]
    assert packs.pick(files)["filename"] == "x-1-cp312-cp312-win_amd64.whl"
    assert packs.pick([{"filename": "x-1.tar.gz"}]) is None


def _wheel(module: str, body: str = "VALUE = 1\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{module}/__init__.py", body)
        z.writestr(f"{module}-1.0.dist-info/METADATA", "Name: x\n")
    return buf.getvalue()


def _fake_pypi(blobs: dict[str, bytes], bad: set[str] = frozenset()):
    """PyPI's JSON and its files, from memory."""
    def fetch(url):
        name = url.split("/pypi/")[1].split("/")[0]
        data = blobs[name]
        digest = "0" * 64 if name in bad else hashlib.sha256(data).hexdigest()
        return {"urls": [{"filename": f"{name}-1.0-py3-none-any.whl", "url": f"https://files/{name}.whl",
                          "size": len(data), "digests": {"sha256": digest}}]}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        name = url.rsplit("/", 1)[1][:-4]
        return Resp(blobs[name])
    return fetch, urlopen


def _pack(**kw) -> packs.Pack:
    return packs.Pack(key="demo", label="Demo", what="does a thing",
                      wheels=(("demopack_a", "1.0"), ("demopack_b", "1.0")), module="demopack_a", **kw)


def test_a_pack_is_downloaded_checked_unpacked_and_importable(home, monkeypatch):
    blobs = {"demopack_a": _wheel("demopack_a", "VALUE = 41\n"), "demopack_b": _wheel("demopack_b")}
    fetch, urlopen = _fake_pypi(blobs)
    pack = _pack()
    monkeypatch.setitem(packs.PACKS, "demo", pack)
    monkeypatch.setattr(packs, "_get_json", fetch)
    monkeypatch.setattr(packs.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(packs, "why_not", lambda p: "")
    p = packs.plan("demo", fetch)
    assert p["can"] and not p["installed"] and p["bytes"] == sum(len(b) for b in blobs.values())
    inst = packs.Installer()
    ok, why = inst.start("demo")
    assert ok, why
    inst._thread.join(10)
    snap = inst.snapshot()
    assert snap["state"] == "done", snap
    assert packs.installed("demo")
    assert (packs.site("demo") / "demopack_a" / "__init__.py").is_file()
    assert not (packs.folder("demo") / "downloads").exists()          # the wheels are not kept
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert packs.activate("demo") and sys.path[-1] == str(packs.site("demo"))
    import demopack_a
    assert demopack_a.VALUE == 41
    sys.modules.pop("demopack_a", None)


def test_a_wheel_that_does_not_arrive_whole_is_refused(home, monkeypatch):
    blobs = {"demopack_a": _wheel("demopack_a"), "demopack_b": _wheel("demopack_b")}
    fetch, urlopen = _fake_pypi(blobs, bad={"demopack_b"})
    monkeypatch.setitem(packs.PACKS, "demo", _pack())
    monkeypatch.setattr(packs, "_get_json", fetch)
    monkeypatch.setattr(packs.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(packs, "why_not", lambda p: "")
    inst = packs.Installer()
    inst.start("demo")
    inst._thread.join(10)
    snap = inst.snapshot()
    assert snap["state"] == "failed" and "did not arrive whole" in snap["error"]
    assert not packs.installed("demo") and not packs.site("demo").exists()


def test_a_machine_that_cannot_use_it_is_told_why_and_nothing_is_fetched(home, monkeypatch):
    monkeypatch.setattr(packs, "nvidia", lambda: False)
    monkeypatch.setattr(packs.os, "name", "nt")
    monkeypatch.setattr(packs, "PY", "cp312")
    p = packs.plan("speech", fetch=lambda url: pytest.fail("asked PyPI for nothing"))
    assert not p["can"] and "NVIDIA" in p["why"]
    ok, why = packs.Installer().start("speech")
    assert not ok and "NVIDIA" in why


def test_models_already_on_disk_are_not_counted(home, monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "why_not", lambda p: "")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    snap = tmp_path / "hub" / "models--Systran--faster-whisper-large-v3" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    fetch = lambda url: {"urls": [{"filename": "w-1-py3-none-any.whl", "url": "u", "size": 10,
                                   "digests": {"sha256": ""}}]}
    p = packs.plan("speech", fetch)
    assert p["models"] == ["large-v3-turbo"]
    assert p["bytes"] == 10 * len(packs.SPEECH.wheels) + packs.SPEECH.models[0].size


def test_an_installed_pack_needs_the_same_pins(home):
    packs.folder("speech").mkdir(parents=True)
    (packs.folder("speech") / "installed.json").write_text(json.dumps({"wheels": [["x", "1"]]}), encoding="utf-8")
    assert not packs.installed("speech")                     # pinned differently: install again
    (packs.folder("speech") / "installed.json").write_text(
        json.dumps({"wheels": [list(w) for w in packs.SPEECH.wheels]}), encoding="utf-8")
    assert packs.installed("speech")


def test_numpy_is_never_in_a_pack():
    """The app carries its own numpy; a second compiled copy cannot load beside it."""
    assert all(name != "numpy" for name, _v in packs.SPEECH.wheels)


def test_speech_looks_in_its_pack(monkeypatch):
    from autostream.clips import speech
    asked = []
    monkeypatch.setattr(packs, "activate", lambda key: asked.append(key) or False)
    speech.models()
    assert asked == ["speech"]


# ---------------------------------------------------------------- the routes

def test_the_routes(home, monkeypatch):
    srv = object.__new__(webui.Server)
    assert srv.packs_plan({"key": "nope"})["error"]
    monkeypatch.setattr(packs, "plan", lambda key: {"key": key, "can": False, "why": "no card"})
    assert srv.packs_plan({"key": "speech"}) == {"ok": True, "key": "speech", "can": False, "why": "no card"}
    assert srv.packs_install({"key": "nope"})["error"] == "There is no such download."
    assert srv.packs_progress()["state"] in ("idle", "done", "failed", "running")


def test_transcribing_without_speech_to_text_asks_for_the_download(tmp_path, monkeypatch):
    from test_highlight_edit import _saved
    from autostream.clips import speech
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda config: tmp_path))
    srv = object.__new__(webui.Server)
    p = _saved(tmp_path)
    Path(p["source"]).write_bytes(b"\0")
    monkeypatch.setattr(speech, "available", lambda: False)
    monkeypatch.setattr(packs, "why_not", lambda pack: "")
    got = srv.clips_highlight_transcribe({"video": p["video"], "track": "game"})
    assert got["need"] == "speech"
    monkeypatch.setattr(packs, "why_not", lambda pack: "needs an NVIDIA graphics card")
    got = srv.clips_highlight_transcribe({"video": p["video"], "track": "game"})
    assert "need" not in got and "NVIDIA" in got["error"]
