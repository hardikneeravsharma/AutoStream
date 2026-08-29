"""Detecting the Edge WebView2 runtime, and why we do not install it silently.

Without the runtime pywebview cannot open a window, so the UI goes to the real
browser instead. A user reported that as a fault -- it is not one, everything
works there -- but nothing in the app said so, which is what made it look like
one.

The runtime is OFFERED, never installed quietly. See webview2.py for the three
reasons; the tests here pin the detection, which is what decides whether the
offer appears at all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                   # noqa: E402

from autostream import webview2                                 # noqa: E402


def test_version_is_a_string_never_a_raise():
    """It is read on the first paint of the wizard. A machine with an odd
    registry must produce a quiet "no", not a stack trace over setup."""
    v = webview2.version()
    assert isinstance(v, str)


def test_installed_agrees_with_version():
    assert webview2.installed() == bool(webview2.version())


def test_a_leftover_uninstall_key_is_not_a_runtime(monkeypatch):
    """EdgeUpdate leaves the client key behind with pv=0.0.0.0 after a
    removal. Treating that as installed would hide the offer from exactly the
    people who need it."""
    import winreg

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(webview2, "_KEYS", (("HKLM", r"SOFTWARE\Fake"),))
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *a: ("0.0.0.0", 1))
    assert webview2.version() == ""


def test_a_real_version_is_returned(monkeypatch):
    import winreg

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(webview2, "_KEYS", (("HKLM", r"SOFTWARE\Fake"),))
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *a: ("151.0.4129.107", 1))
    assert webview2.version() == "151.0.4129.107"


def test_installing_when_it_is_already_there_downloads_nothing(monkeypatch):
    """Pressing the button twice, or on a machine that already has it, must
    not fetch or run an installer."""
    monkeypatch.setattr(webview2, "version", lambda: "151.0.4129.107")
    called = []
    monkeypatch.setattr(webview2.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    r = webview2.install()
    assert r["ok"] is True
    assert r.get("already") is True
    assert called == [], "it went to the network anyway"


def test_a_tiny_download_is_refused(monkeypatch):
    """A captive portal or a redirect page returns HTML with a 200. Running
    that as an executable is worse than not installing anything."""
    monkeypatch.setattr(webview2, "version", lambda: "")

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>sign in to the wifi</html>"

    monkeypatch.setattr(webview2.urllib.request, "urlopen",
                        lambda *a, **k: FakeResp())
    ran = []
    monkeypatch.setattr(webview2.subprocess, "run",
                        lambda *a, **k: ran.append(1))
    r = webview2.install()
    assert r["ok"] is False
    assert ran == [], "it executed the download anyway"


def test_the_bootstrapper_is_microsofts_own_link():
    """Fetching an executable means the source has to be beyond question."""
    assert webview2.BOOTSTRAPPER.startswith("https://go.microsoft.com/")
