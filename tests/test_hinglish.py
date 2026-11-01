"""Hinglish captions: Hindi written in Latin letters, the way the player's viewers
read it (clips/hinglish.py). His example: "clove is down" said in Hindi is to be
written "clove neeche hai"."""
from __future__ import annotations

import pytest

from autostream.clips import hinglish as h


@pytest.mark.parametrize("said, written", [
    ("क्लोव नीचे है", "Clove neeche hai"),                       # the player's own example
    ("क्या जरुरोत है प्लांट करने की उधर", "Kya jarurot hai plant karne ki udhar"),
    ("नहीं भाई, अपना काम करो", "Nahin bhai, apna kaam karo"),
    ("रुको रुको रुको आने दो", "Ruko ruko ruko aane do"),
    ("मैं समझ गया", "Main samajh gaya"),
    ("मैंने बोला था", "Maine bola tha"),
    ("स्पाइक डिफ्यूज़ करो जल्दी", "Spike defuse karo jaldi"),
    ("हेवन गया, मिक्स", "Heaven gaya, mix"),
    ("बहुत बढ़िया शॉट", "Bahut badhiya shot"),
])
def test_hindi_is_written_the_way_it_is_typed(said, written):
    assert h.romanize(said) == written


def test_english_and_numbers_are_left_alone():
    assert h.romanize("Not A, don't peak in mid") == "Not A, don't peak in mid"
    assert h.romanize("3 लोग B पे") == "3 log B pe"


def test_common_hindi_words_are_not_taken_for_english():
    """The first matcher turned करदे into "corrode", सारे into "sorry", वाले into
    "wall" and मैंने into "main" -- by their consonants alone."""
    assert h.romanize("कर दे सारे वाले बाकी") == "Kar de saare vaale baaki"


def test_the_danda_ends_a_sentence():
    assert h.romanize("चलो। अब जाओ") == "Chalo. Ab jao"
