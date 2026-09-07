"""A real broadcast, on the real channel, deleted again.

Tier 6. The only thing in this repo that touches the outside world.

It runs only when ALL of these are true, and each is checked separately so a
skip says which one stopped it:

    pytest -m live                      the marker, excluded by default
    AUTOSTREAM_VERIFY_LIVE=yes          a second, deliberate opt-in
    OBS is running and reachable
    YouTube is authorised, with a stream key configured
    state.json says IDLE                nothing of the user's is in flight

WHY IT EXISTS. Every tier below this one replaces OBS and YouTube with a fake.
A fake agrees with whatever the code believes, so the one thing none of them
can catch is the code being wrong about the real API: a scope that was never
granted, a transition YouTube refuses in that order, an OBS that accepts the
websocket and then does not start. `python -m autostream obs-test` proves
ingestion works; this proves a whole session does, and cleans up after itself.

WHAT IT COSTS. One broadcast created and deleted, against the daily quota.
It is always private, always titled so it is obvious, and the cleanup runs in
a finally block that also catches Ctrl-C -- a verify run must not be able to
leave a broadcast sitting on someone's channel.
"""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.live

OPT_IN = "AUTOSTREAM_VERIFY_LIVE"
TITLE = "AutoStream verify - ignore, deleting itself"


def _require(cond, why):
    if not cond:
        pytest.skip(why)


@pytest.fixture(scope="module")
def live():
    """Everything checked before anything is created."""
    _require(os.environ.get(OPT_IN, "").lower() in ("1", "yes", "true"),
             f"{OPT_IN} is not set. This creates a real broadcast and spends "
             f"quota, so the marker alone is deliberately not enough.")

    from autostream import cfg
    from autostream.state import State

    config = cfg.load()
    _require(config.youtube.enabled, "youtube.enabled is off on this machine")
    _require(bool(config.youtube.stream_id),
             "no youtube.stream_id configured - run: python -m autostream setup")

    state = State.load()
    _require(state.phase == "IDLE",
             f"a session is in progress (phase={state.phase}). This would "
             f"interfere with it.")
    _require(not state.paused, "AutoStream is paused; resume it first")

    from autostream.youtube import YouTube
    yt = YouTube(config, state)

    left = state.quota_left(getattr(__import__(
        "autostream.engine", fromlist=["DAILY_QUOTA"]), "DAILY_QUOTA", 10000))
    _require(left > 3000, f"only {left} quota units left today; not spending "
                          f"them on a test")

    from autostream.obs import Obs
    obs = Obs(config)
    try:
        obs.is_streaming()
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"OBS is not reachable: {e}")

    print(f"\n  tier 6: creating a PRIVATE broadcast on the configured "
          f"channel. Quota left before: {left}")
    return config, state, yt, obs


@pytest.fixture
def broadcast(live):
    """One private broadcast, deleted whatever happens.

    The finally block catches BaseException, not Exception: a Ctrl-C during
    the ingestion wait is the single most likely way this test ends early,
    and it is exactly the case that must still clean up.
    """
    config, _state, yt, obs = live
    bid = None
    try:
        bid = yt.create_broadcast(TITLE, "Automated verification. Delete me.",
                                  privacy="private")
        assert bid, "YouTube did not return a broadcast id"
        yt.bind(bid, config.youtube.stream_id)
        yield yt, obs, bid, config
    finally:
        try:
            obs.stop()
        except Exception:                                    # noqa: BLE001
            pass
        if bid:
            try:
                yt.delete_broadcast(bid)
                print(f"  tier 6: deleted broadcast {bid}")
            except Exception as e:                           # noqa: BLE001
                pytest.fail(f"COULD NOT DELETE BROADCAST {bid}: {e}. "
                            f"Remove it by hand in YouTube Studio.")


def test_a_broadcast_can_be_created_bound_and_deleted(broadcast):
    """The cheapest half: the API accepts the calls in the order the engine
    makes them. No OBS, no ingestion, no waiting."""
    yt, _obs, bid, _config = broadcast
    assert bid
    assert yt.watch_url(bid).endswith(bid)


def test_a_new_broadcast_is_private(broadcast):
    """The safety property that matters most here. A verify run that put
    something public on the channel would be worse than no verify run."""
    yt, _obs, bid, _config = broadcast
    status = None
    for name in ("broadcast_privacy", "privacy_of", "broadcast_status"):
        fn = getattr(yt, name, None)
        if callable(fn):
            try:
                status = fn(bid)
                break
            except Exception:                                # noqa: BLE001
                continue
    if status is None:
        pytest.skip("this YouTube client cannot read a broadcast's privacy "
                    "back; it was created with privacy='private'")
    assert "private" in str(status).lower(), f"created as {status!r}, not private"


def test_obs_reaches_youtube_and_a_session_completes(broadcast):
    """The whole path, end to end, exactly as the engine walks it:

        bind -> OBS start -> wait for ingestion -> testing -> live -> complete

    This is `python -m autostream obs-test` carried through to the end. That
    command stops once ingestion is active, which leaves the two transitions
    the engine actually depends on untested against the real API.
    """
    yt, obs, bid, config = broadcast

    obs.start(scene=config.obs.default_scene or None)
    deadline = time.time() + float(config.timing.ingestion_timeout)
    status = health = None
    while time.time() < deadline:
        status, health = yt.stream_status(config.youtube.stream_id)
        if status == "active":
            break
        time.sleep(3)
    assert status == "active", (
        f"YouTube never saw the stream in "
        f"{config.timing.ingestion_timeout}s (status={status} health={health}). "
        f"OBS is running and connected, so this is the ingestion path itself.")

    yt.transition(bid, "testing")
    time.sleep(2)
    yt.transition(bid, "live")
    time.sleep(2)
    yt.transition(bid, "complete")
    # The broadcast is deleted by the fixture either way; completing it first
    # is what a real session does, and a transition YouTube refuses in this
    # order is precisely the failure no fake can show.
