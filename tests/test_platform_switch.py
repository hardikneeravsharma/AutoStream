"""Changing platform, and the two ways it quietly did not take effect.

The dashboard grew a platform chooser, which saves `youtube.platform` and
expects the engine to follow. It did not, for two separate reasons, and
neither announced itself: the config said Twitch, the page said Twitch, the
stored value said Twitch, and the engine went on talking to YouTube.

NO MODULE RELOADS HERE. The first version of this file called
`importlib.reload` on paths, cfg and webui to point them at a temp home, and
the reloaded modules outlived the test -- three engine-flow tests in another
file then failed, but only when the whole suite ran in one process. Patching
the two path attributes does the same job and leaves nothing behind.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from autostream import cfg, paths, webui
from autostream.engine import Engine


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway install with nothing in it but a config file."""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "CONFIG_FILE", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(paths, "TOKEN_FILE", tmp_path / "secrets" / "token.json")
    monkeypatch.setattr(paths, "STATE_FILE", tmp_path / "state.json")
    return tmp_path


def _write(home: pathlib.Path, platform: str, **extra) -> None:
    values = {"enabled": True, "platform": platform, "stream_id": "x"}
    values.update(extra)
    (home / "config" / "config.yaml").write_text(
        yaml.safe_dump({"youtube": values}), encoding="utf-8")


@pytest.fixture
def eng(home):
    _write(home, "youtube")
    return Engine(cfg.load()), home


# ---------------------------------------------------- it follows the config

def test_it_starts_on_what_the_config_says(eng):
    e, _ = eng
    assert e.platform.name == "youtube"


def test_a_saved_change_takes_effect_without_a_restart(eng):
    """THE REPORTED SHAPE. Every other key is picked up by refreshing the
    config object in place on the next tick. This one had already been read
    into a platform object at startup, which outlived it -- so the only
    symptom was a stream going to the wrong service, with nothing logged and
    nothing failing."""
    e, home = eng
    _write(home, "twitch")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "twitch"


def test_it_goes_back_again(eng):
    e, home = eng
    _write(home, "kick")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "kick"
    _write(home, "youtube")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "youtube"


def test_an_unknown_name_falls_back_rather_than_failing_to_start(eng):
    e, home = eng
    _write(home, "myspace")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "youtube"


# ------------------------------------------------------- but never mid-stream

def test_a_live_session_keeps_the_platform_it_began_on(eng):
    """A swap while a stream is up leaves OBS pushing to one service and the
    engine retitling and ending a session on another. The stream stays up, so
    nothing looks wrong until the title never changes and the VOD never
    appears."""
    e, home = eng
    e.state.broadcast_id = "abc123"
    _write(home, "twitch")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "youtube", "switched out from under a live stream"


def test_and_applies_it_once_that_session_ends(eng):
    e, home = eng
    e.state.broadcast_id = "abc123"
    _write(home, "twitch")
    cfg.refresh_in_place(e.cfg)
    e.state.broadcast_id = ""
    e.session = None
    assert e.platform.name == "twitch"


def test_asking_where_to_watch_does_not_invent_a_session(eng):
    """THE BUG THAT HID THE FIRST ONE. `_session()` rebuilds a session from
    `state.broadcast_id` after a restart, and memoised what it built. Asked
    with no broadcast id it stored an EMPTY session, so `self.session` became
    non-None on the first call and stayed that way.

    The first caller is the two-second status poll, which asks for the watch
    url. Every later test of "is a session in flight" then answered yes --
    including the platform switch, which refused to apply because it believed
    a stream was up. Nothing was live; nothing said so."""
    e, home = eng
    e.state.broadcast_id = ""
    e._watch_url()
    assert e.session is None, "an empty session was cached by a read"

    _write(home, "twitch")
    cfg.refresh_in_place(e.cfg)
    assert e.platform.name == "twitch"


def test_a_session_rebuilt_after_a_restart_is_still_kept(eng):
    """The memoisation is worth having when there IS something to remember."""
    e, _ = eng
    e.state.broadcast_id = "abc123"
    first = e._session()
    assert first.handle == "abc123"
    assert e._session() is first


# ------------------------------------------- the wizard that stood in the way

@pytest.mark.parametrize("platform,wanted", [
    ("youtube", False),     # no token, no stream: setup really is unfinished
    ("twitch", True),
    ("kick", True),
])
def test_only_youtube_needs_a_google_sign_in_before_the_app_opens(
        home, platform, wanted):
    """`is_configured` gates the setup wizard on a YouTube permanent stream
    and a Google credential. A Twitch user owns neither and has no reason to,
    so picking Twitch left them held in a wizard asking them to sign in to
    Google for a service they were not going to use -- with their actual
    sign-in on the Settings page the wizard was standing in front of."""
    (home / "config" / "config.yaml").write_text(
        yaml.safe_dump({"youtube": {"enabled": True, "platform": platform}}),
        encoding="utf-8")
    assert webui.is_configured() is wanted


def test_a_clips_only_install_still_skips_the_wizard(home):
    """The older escape hatch, which this must not have broken."""
    (home / "config" / "config.yaml").write_text(
        yaml.safe_dump({"youtube": {"enabled": False}}), encoding="utf-8")
    assert webui.is_configured() is True


# --------------------------------------- waiting for ingestion is YouTube's

class _Counting:
    """A platform that records whether the engine asked it about ingestion."""

    def __init__(self, waits: bool) -> None:
        from autostream.platforms import Capabilities

        self.name = "counting"
        self.label = "Counting"
        self.caps = Capabilities(waits_for_ingest=waits, has_preview=waits)
        self.asked = 0

    def ingest_live(self, session) -> bool:
        self.asked += 1
        return False                      # never yet seen by the service

    def go_preview(self, session) -> None: ...
    def go_live(self, session) -> None: ...


def _starting(eng, platform):
    from autostream import state as stt

    eng.platform = platform
    eng.state.phase = stt.STARTING
    eng.state.broadcast_id = "bid-1"
    eng._starting_deadline = None
    eng._start_failures = 0
    eng.streaming = False     # _go_live then just moves the phase; OBS is not here
    return stt


def test_a_platform_that_waits_is_asked_whether_the_stream_arrived(eng):
    """YouTube's broadcast is a real object that cannot be transitioned until
    it has received frames, so this poll is the whole point of STARTING."""
    e, _ = eng
    pl = _Counting(waits=True)
    stt = _starting(e, pl)
    e._tick_starting()
    assert pl.asked == 1
    assert e.state.phase == stt.STARTING, "moved on before the stream arrived"


def test_a_platform_that_does_not_wait_is_never_asked(eng):
    """Twitch and Kick are live the moment RTMP arrives -- there is nothing to
    transition, and their stream listings lag by up to a minute. Polled anyway,
    STARTING could outlast `ingestion_timeout` and abandon a session that was
    already on air, reporting that the service never saw the ingestion.

    The capability flag said not to ask. The engine was not reading it."""
    e, _ = eng
    pl = _Counting(waits=False)
    stt = _starting(e, pl)
    e._tick_starting()
    assert pl.asked == 0, "asked a platform that declared it does not wait"
    assert e.state.phase == stt.LIVE


@pytest.mark.parametrize("name,waits", [("twitch", False), ("kick", False)])
def test_the_real_platforms_declare_they_do_not_wait(eng, home, name, waits):
    """Asserted against the shipped objects, not a stand-in, so a capability
    edited in one of them fails here rather than at a go-live."""
    e, _ = eng
    _write(home, name)
    cfg.refresh_in_place(e.cfg)
    assert e.platform.caps.waits_for_ingest is waits


def test_youtube_still_waits(eng):
    e, _ = eng
    assert e.platform.caps.waits_for_ingest is True


def test_the_abort_message_names_the_platform_it_was_waiting_on(eng, monkeypatch):
    """It said "YouTube never saw our ingestion" whichever service was in use."""
    import time as _t

    from autostream import engine as eng_mod
    from autostream import state as stt

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(" ".join(str(x) for x in a)))
    e, _ = eng
    pl = _Counting(waits=True)
    pl.label = "Hypothetical"
    _starting(e, pl)
    e._starting_deadline = _t.monotonic() - 1
    e._abandon_start = lambda: e._goto(stt.IDLE)
    e._tick_starting()
    assert said and "Hypothetical" in said[0], said
    assert "YouTube" not in said[0]


# ------------------------------------------- ready(), which the poll asks

def test_ready_is_not_preflight(eng, home, caplog):
    """FROM A BUG CAUGHT BEFORE IT SHIPPED. The dashboard asked `preflight`
    on every two-second status poll, and Twitch's preflight warns when it is
    not connected -- thirty lines a minute, in a log read after something has
    gone wrong. `ready` says the same thing and writes nothing."""
    import logging

    e, _ = eng
    _write(home, "twitch")
    cfg.refresh_in_place(e.cfg)
    pl = e.platform

    # Cleared here, not at the top: building the platform logs that it
    # changed, which is correct and happens once.
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        for _ in range(30):
            pl.ready()
    assert caplog.records == [], (
        "ready() logged; thirty polls a minute would flood the log")


@pytest.mark.parametrize("name", ["youtube", "twitch", "kick"])
def test_every_platform_answers_ready_with_a_reason(eng, home, name,
                                                     monkeypatch):
    """An unset-up install must say which one it is and what is missing, in
    a sentence the dashboard can print without rewriting.

    The credential files are pointed at the empty home explicitly. They are
    module-level and resolve against AUTOSTREAM_HOME at import, which under
    the suite is the repo -- where a developer's own twitch.json lives, and
    where this read "configured" and passed for the wrong reason."""
    from autostream.platforms import kick as kk
    from autostream.platforms import twitch as tw

    for mod, who in ((tw, "twitch"), (kk, "kick")):
        monkeypatch.setattr(mod, "CRED_FILE", home / f"{who}-absent.json")
        monkeypatch.setattr(mod, "TOKEN_FILE", home / f"{who}-no-token.json")

    e, _ = eng
    _write(home, name)
    cfg.refresh_in_place(e.cfg)
    ok, why = e.platform.ready()
    assert ok is False, "nothing is configured in this home"
    assert why, "refused with no reason"
    assert e.platform.label.split()[0].lower() in why.lower()


def test_twitch_can_go_live_on_the_key_alone(eng, home, monkeypatch):
    """LIVE WITH A STALE TITLE BEATS NOT LIVE. The key is what makes the
    broadcast happen; the token only sets title and category. Treating a
    missing sign-in as a refusal would cost a stream to save a title."""
    import json

    from autostream.platforms import twitch as tw

    cred = home / "twitch.json"
    cred.write_text(json.dumps({"client_id": "a" * 30,
                                "client_secret": "b" * 30,
                                "stream_key": "live_fake"}), encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    monkeypatch.setattr(tw, "TOKEN_FILE", home / "absent.json")

    ok, why = tw.Twitch().ready()
    assert ok is True
    assert "not signed in" in why, "it still has to say the title will not be set"


def test_kick_cannot_because_the_key_comes_from_the_api(eng, home, monkeypatch):
    """The difference between the two, asserted so a shared base class can
    never quietly make them the same."""
    import json

    from autostream.platforms import kick as kk

    cred = home / "kick.json"
    cred.write_text(json.dumps({"client_id": "a" * 26,
                                "client_secret": "b" * 64}), encoding="utf-8")
    monkeypatch.setattr(kk, "CRED_FILE", cred)
    monkeypatch.setattr(kk, "TOKEN_FILE", home / "absent.json")

    ok, why = kk.Kick().ready()
    assert ok is False
    assert "stream key through the API" in why


def test_preflight_still_refuses_what_ready_refuses(eng, home, monkeypatch):
    """The two must not drift: `ready` is now what `preflight` asks."""
    import json

    from autostream.platforms import NotConfigured
    from autostream.platforms import kick as kk

    cred = home / "kick.json"
    cred.write_text(json.dumps({"client_id": "a" * 26,
                                "client_secret": "b" * 64}), encoding="utf-8")
    monkeypatch.setattr(kk, "CRED_FILE", cred)
    monkeypatch.setattr(kk, "TOKEN_FILE", home / "absent.json")

    k = kk.Kick()
    ok, why = k.ready()
    assert ok is False
    with pytest.raises(NotConfigured) as e:
        k.preflight()
    assert str(e.value) == why
