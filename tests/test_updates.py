"""Finding and fetching a newer AutoStream.

The package is unsigned, GitHub serves it through a redirect to a CDN, and a
truncated download looks exactly like a complete one. So the interesting cases
here are all about refusing: a version that is not newer, an asset that is not
there, and a download whose checksum does not match what the release published.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import updates                         # noqa: E402


# ------------------------------------------------------------ versions

def test_a_newer_version_is_recognised():
    assert updates.is_newer("1.7.0", "1.6.9")
    assert updates.is_newer("2.0.0", "1.9.9")
    assert not updates.is_newer("1.6.9", "1.7.0")
    assert not updates.is_newer("1.7.0", "1.7.0")


def test_versions_compare_as_numbers_not_as_text():
    """"1.10.0" is newer than "1.9.9", and a string comparison says otherwise."""
    assert updates.is_newer("1.10.0", "1.9.9")
    assert updates.is_newer("v1.10.0", "v1.9.9")
    assert not updates.is_newer("1.9.9", "1.10.0")


def test_a_leading_v_is_not_part_of_the_number():
    assert not updates.is_newer("v1.7.0", "1.7.0")
    assert updates.parse_version("v1.7.0") == updates.parse_version("1.7.0")


def test_something_unparseable_is_not_treated_as_newer():
    assert not updates.is_newer("", "1.0.0")
    assert not updates.is_newer("nightly", "1.0.0")


# ------------------------------------------------------------ the release

def _release_json(tag="v1.8.0", with_sum=True):
    assets = [{"name": "AutoStream-share.zip",
               "browser_download_url": "https://example.invalid/a.zip",
               "size": 123}]
    if with_sum:
        assets.append({"name": "AutoStream-share.zip.sha256",
                       "browser_download_url": "https://example.invalid/a.sha256",
                       "size": 80})
    return {"tag_name": tag, "html_url": "https://example.invalid/rel",
            "body": "notes here", "published_at": "2026-09-02T00:00:00Z",
            "assets": assets}


def test_the_release_is_read_out_of_githubs_answer(monkeypatch):
    import json as _json

    monkeypatch.setattr(updates, "_get",
                        lambda url, accept=None: _json.dumps(_release_json()).encode())
    rel = updates.latest()
    assert rel.version == "1.8.0" and rel.tag == "v1.8.0"
    assert rel.asset_url.endswith("a.zip")
    assert rel.sha256_url.endswith("a.sha256")
    assert rel.usable


def test_a_release_with_no_package_is_not_usable(monkeypatch):
    import json as _json

    data = _release_json()
    data["assets"] = [{"name": "something-else.txt",
                       "browser_download_url": "x", "size": 1}]
    monkeypatch.setattr(updates, "_get",
                        lambda url, accept=None: _json.dumps(data).encode())
    assert not updates.latest().usable


def test_rate_limiting_is_reported_as_itself(monkeypatch):
    import urllib.error

    def limited(url, accept=None):
        raise urllib.error.HTTPError(url, 403, "rate limited", {}, None)

    monkeypatch.setattr(updates, "_get", limited)
    with pytest.raises(RuntimeError, match="rate-limiting"):
        updates.latest()


def test_being_offline_is_reported_as_itself(monkeypatch):
    import urllib.error

    def offline(url, accept=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(updates, "_get", offline)
    with pytest.raises(RuntimeError, match="Could not reach GitHub"):
        updates.latest()


# ------------------------------------------------------------ downloading

class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self._at = 0

    def read(self, n=-1):
        chunk = self._payload[self._at:self._at + (n if n and n > 0 else len(self._payload))]
        self._at += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, payload, checksum):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=None, context=None: _Response(payload))
    monkeypatch.setattr(updates, "published_sha256", lambda rel: checksum)


def _rel():
    return updates.Release(version="1.8.0", tag="v1.8.0",
                           asset_url="https://example.invalid/a.zip",
                           asset_name="AutoStream-share.zip",
                           sha256_url="https://example.invalid/a.sha256")


def test_a_good_download_is_kept(tmp_path, monkeypatch):
    payload = b"pretend this is 168 megabytes"
    _serve(monkeypatch, payload, hashlib.sha256(payload).hexdigest())
    got = updates.download(_rel(), tmp_path)
    assert got.read_bytes() == payload
    assert got.name == "AutoStream-share.zip"


def test_a_download_that_does_not_match_the_checksum_is_thrown_away(tmp_path, monkeypatch):
    """Half a download that looks like an update is worse than no update."""
    _serve(monkeypatch, b"corrupted", "0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        updates.download(_rel(), tmp_path)
    assert list(tmp_path.iterdir()) == [], "the bad file was kept"


def test_a_release_with_no_checksum_still_downloads_but_says_so(tmp_path, monkeypatch, caplog):
    import logging

    payload = b"unverifiable"
    _serve(monkeypatch, payload, "")
    with caplog.at_level(logging.WARNING, logger="autostream.updates"):
        got = updates.download(_rel(), tmp_path)
    assert got.exists()
    assert "could not be verified" in caplog.text


def test_a_cancelled_download_leaves_nothing_behind(tmp_path, monkeypatch):
    _serve(monkeypatch, b"x" * 4096, "")
    with pytest.raises(RuntimeError, match="cancelled"):
        updates.download(_rel(), tmp_path, should_stop=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_progress_is_reported(tmp_path, monkeypatch):
    payload = b"y" * 2048
    _serve(monkeypatch, payload, hashlib.sha256(payload).hexdigest())
    seen = []
    updates.download(_rel(), tmp_path, on_progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == len(payload)


def test_a_release_with_nothing_to_download_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="no downloadable"):
        updates.download(updates.Release(), tmp_path)


# ------------------------------------------- which asset a release hands over

def _both_json(tag="v1.8.0"):
    """A release carrying the installer and the zip, as builds now produce."""
    data = _release_json(tag=tag)
    data["assets"] += [
        {"name": "AutoStream-1.8.0-setup.exe",
         "browser_download_url": "https://example.invalid/setup.exe",
         "size": 111_000_000},
        {"name": "AutoStream-1.8.0-setup.exe.sha256",
         "browser_download_url": "https://example.invalid/setup.sha256",
         "size": 80},
    ]
    return data


def test_the_installer_is_chosen_over_the_zip(monkeypatch):
    """Only the installer can replace a running program."""
    import json as _json

    monkeypatch.setattr(updates, "_get",
                        lambda url, accept=None: _json.dumps(_both_json()).encode())
    rel = updates.latest()
    assert rel.asset_name == "AutoStream-1.8.0-setup.exe"
    assert rel.installable
    # ...and the checksum that belongs to THAT file, not the zip's.
    assert rel.sha256_url.endswith("setup.sha256")


def test_a_release_with_only_a_zip_still_works(monkeypatch):
    """Older releases predate the installer and must stay downloadable."""
    import json as _json

    monkeypatch.setattr(updates, "_get",
                        lambda url, accept=None: _json.dumps(_release_json()).encode())
    rel = updates.latest()
    assert rel.asset_name == "AutoStream-share.zip"
    assert not rel.installable
    assert rel.usable


def test_the_newest_installer_wins_if_a_release_carries_several(monkeypatch):
    import json as _json

    data = _both_json()
    data["assets"].append(
        {"name": "AutoStream-1.7.9-setup.exe",
         "browser_download_url": "https://example.invalid/old.exe", "size": 1})
    monkeypatch.setattr(updates, "_get",
                        lambda url, accept=None: _json.dumps(data).encode())
    # Sorted by name, so 1.8.0 sorts after 1.7.9; the point is that one is
    # picked deterministically rather than by dictionary order.
    assert updates.latest().asset_name == "AutoStream-1.8.0-setup.exe"


# ------------------------------------------------ saying so when there is
# nothing to say
#
# "Check for updates" answering with silence was reported as the button being
# broken. It was not: the machine was running a build newer than the newest
# release, so there was correctly nothing to offer -- and the page then
# cleared its own message, which also hides the panel the message sits in. An
# answer nobody can see is the same as no answer.

def _settings_js() -> str:
    from autostream.ui import settings

    return settings.SETTINGS_JS


def test_the_up_to_date_answer_is_not_cleared():
    js = _settings_js()
    i = js.index("function set_verRender(")
    j = js.index("\nfunction ", i + 1)
    body = js[i:j]
    # The branch that runs when there is no update must SAY something.
    assert "set_verSay('')" not in body, (
        "clearing the message also hides the panel it is in, so the answer "
        "'you are up to date' arrives as a button that appears to do nothing")
    assert "latest release" in body


def test_a_build_newer_than_the_release_is_explained():
    """The case that prompted this: 1.10.0 running against a 1.9.1 release.
    'No update' is true and baffling, so it is spelled out."""
    js = _settings_js()
    assert "set_verAhead" in js
    assert "NEWER than the latest" in js


def test_versions_are_compared_as_numbers_in_the_page_too():
    """1.9.1 sorts ABOVE 1.10.0 as text, which is exactly backwards -- and
    would have claimed the newer build was the older one."""
    js = _settings_js()
    i = js.index("function set_verNum(")
    j = js.index("\nfunction ", i + 1)
    body = js[i:j]
    assert "Number(" in body and "1e6" in body, (
        "set_verNum must parse the parts as numbers rather than comparing "
        "version strings")
