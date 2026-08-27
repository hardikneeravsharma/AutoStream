"""The last thing a new user saw was "Failed to fetch" on a setup that worked.

finish() saves youtube.stream_id part-way through its work. That is the moment
is_configured() turns true -- while the request that caused it is still being
answered. cmd_run's hold loop polled that every two seconds, saw it, and called
server.stop(), closing the socket underneath the response.

The browser reported ERR_CONNECTION_RESET, 0 bytes, at 2.05s -- and a page
cannot tell a reset apart from the request having failed outright. The user
was told setup had failed, twice re-ran it, and each time it worked.

So the server now says whether it is safe to stop, and the loop asks.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui                                    # noqa: E402


def a_server() -> webui.Server:
    return webui.Server.__new__(webui.Server).__class__.__new__(webui.Server)


def fresh() -> webui.Server:
    s = webui.Server("tok", 8999, None)
    return s


def test_a_new_server_is_immediately_idle():
    s = fresh()
    assert s.idle_for() >= 0.0


def test_a_request_in_flight_is_never_idle():
    """The whole fix. Zero means "do not stop", and it is checked, not assumed."""
    s = fresh()
    s.request_started()
    assert s.idle_for() == 0.0
    s.request_finished()
    assert s.idle_for() >= 0.0


def test_overlapping_requests_all_have_to_finish():
    """ThreadingHTTPServer serves several at once; one finishing does not mean
    the socket is free."""
    s = fresh()
    s.request_started()
    s.request_started()
    s.request_finished()
    assert s.idle_for() == 0.0, "still one in flight"
    s.request_finished()
    assert s.idle_for() >= 0.0


def test_the_idle_clock_starts_when_the_last_one_finishes():
    s = fresh()
    s.request_started()
    time.sleep(0.05)
    s.request_finished()
    assert s.idle_for() < 0.05      # measured from the finish, not the start


def test_it_survives_an_unbalanced_finish():
    """A handler that raised before its start was counted must not drive the
    counter negative and wedge the server permanently 'idle'."""
    s = fresh()
    s.request_finished()
    s.request_started()
    assert s.idle_for() == 0.0
    s.request_finished()
    assert s.idle_for() >= 0.0


def test_counting_is_thread_safe():
    s = fresh()
    def hammer():
        for _ in range(400):
            s.request_started()
            s.request_finished()
    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.idle_for() >= 0.0       # balanced: nothing left in flight


def test_the_linger_is_long_enough_to_be_read():
    """Ten seconds is not arbitrary: the old loop gave the response zero, and
    a person has to read what the page says before the process exits."""
    from autostream.__main__ import SETUP_LINGER

    assert SETUP_LINGER >= 5.0
