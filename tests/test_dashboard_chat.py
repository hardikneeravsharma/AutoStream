"""Live chat on the Dashboard's right half.

The player's words: "the live chats should be more focused, it is important".
Three things were agreed for it (docs/superpowers/specs/2026-10-29-ui-redesign-design.md):
a viewer's !clip becomes its own row with a Watch link, a first message is
marked so it can be greeted, and a pill counts what arrived while you were
scrolled up. The row-building is a pure function, tested here in Node.
"""
from __future__ import annotations

import json

from autostream import ui, webui
from tests import jsfn


def rows(msgs, marks=(), seen=(), live=True):
    expr = f"dash_chatRows({json.dumps(list(msgs))}, {json.dumps(list(marks))}, {json.dumps(list(seen))}, {json.dumps(live)})"
    return jsfn.call(ui.JS, ["dash_chatRows"], expr)


def test_a_first_message_is_marked_once():
    got = rows([{"id": 1, "author": "a", "text": "hi"}, {"id": 2, "author": "b", "text": "yo"},
                {"id": 3, "author": "a", "text": "again"}])
    assert [r["first"] for r in got] == [True, True, False]


def test_someone_already_seen_is_not_first():
    got = rows([{"id": 1, "author": "a", "text": "hi"}], seen=["a"])
    assert got[0]["first"] is False


def test_a_clip_request_becomes_a_mark_row_at_its_moment():
    got = rows([{"id": 1, "author": "rav3n", "text": "!clip"}],
               marks=[{"at": 5020.0, "author": "rav3n"}])
    assert got == [{"kind": "mark", "id": "1", "author": "rav3n", "at": 5020.0,
                    "time": got[0]["time"], "watch": "after"}]


def test_after_the_stream_the_mark_can_be_watched_now():
    got = rows([{"id": 1, "author": "rav3n", "text": "!clip"}],
               marks=[{"at": 12.5, "author": "rav3n"}], live=False)
    assert got[0]["watch"] == "now"


def test_two_requests_take_their_own_marks_in_order():
    got = rows([{"id": 1, "author": "r", "text": "!clip"}, {"id": 2, "author": "r", "text": "!clip"}],
               marks=[{"at": 10, "author": "r"}, {"at": 70, "author": "r"}])
    assert [r["at"] for r in got] == [10, 70]


def test_a_request_the_app_ignored_stays_a_message():
    # The engine drops a !clip it could not place (not recording, or the
    # same viewer inside the cooldown). Showing a mark for it would be a lie.
    got = rows([{"id": 1, "author": "r", "text": "!clip"}], marks=[])
    assert got[0]["kind"] == "msg"


def test_badges_are_words():
    got = rows([{"id": 1, "author": "m", "text": "x", "mod": True},
                {"id": 2, "author": "o", "text": "y", "owner": True}])
    assert [r["badge"] for r in got] == ["Mod", "Host"]


def test_the_status_carries_the_marks():
    class E:
        _marks = [{"at": float(i), "author": "v"} for i in range(80)]
    got = webui.chat_marks(E())
    assert len(got) == 60 and got[-1] == {"at": 79.0, "author": "v"}
    assert webui.chat_marks(object()) == []


def test_the_chat_has_its_pill_and_its_hint():
    assert 'id="dash-chat-new"' in ui.BODY
    assert 'id="dash-chat-hint"' in ui.BODY
