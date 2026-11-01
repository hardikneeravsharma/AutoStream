"""Hindi in Latin letters, the way players type it: "क्लोव नीचे है" -> "clove neeche hai".

WHY THIS EXISTS
    The player (2026-11-02): "make all the captions hinglish -- if someone says in
    Hindi that clove is down then actually write: clove neeche hai". His viewers
    read Hinglish; the Devanagari speech-to-text writes is not what they read, and
    the English translation is not what he said.

WHY BY RULE AND NOT BY THE MODEL
    Measured first (20 of his lines, 2026-11-02): asked for Latin letters, Whisper
    does write Hinglish -- but only with a prompt in Hinglish, and every prompt
    tried LEAKED into the output ("Spike plant ho gaya, defuse kar." written over
    a line about a Spectre; four prompts, all leaking, the short ones drifting into
    English instead). Writing out the Devanagari it already heard, letter by letter,
    never invents a word, costs nothing, and works on every project already made.

HOW
    Each akshara becomes its usual chat spelling (नी nee, चे che, है hai); the
    inherent "a" is dropped where Hindi drops it (word-final, and between a vowel
    and a consonant-vowel: करना karna, अपना apna); a word-final aa / ee / oo is
    written short (क्या kya, जल्दी jaldi). English and game words said in Hindi
    come back as their English spelling when their sound matches one in ENGLISH
    (प्लांट -> plant, स्पाइक -> spike). Latin text is left exactly as it is.
"""
from __future__ import annotations

import re

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ळ": "l", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y",
}
NUKTA = "़"
NUKTA_FORMS = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़", "ढ": "ढ़", "फ": "फ़", "य": "य़"}
VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
          "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऍ": "e", "ऑ": "o", "ऎ": "e", "ऒ": "o"}
MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
          "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
          "ॆ": "e", "ॊ": "o"}
HALANT = "्"
ANUSVARA, CANDRA, VISARGA = "ं", "ँ", "ः"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Game and English words a Hindi-speaking player says in English: Valorant's
# agents, maps, guns, callouts, and the English of a match. Matched by sound
# (_key), so स्पाइक and स्पाईक both come back as "spike".
ENGLISH = """
astra breach brimstone chamber clove cypher deadlock fade gekko harbor iso jett kayo killjoy neon omen
phoenix raze reyna sage skye sova tejo viper vyse waylay yoru
abyss ascent bind breeze corrode fracture haven icebox lotus pearl split sunset summit
vandal phantom operator op sheriff ghost classic frenzy shorty judge bucky spectre stinger odin ares
marshal outlaw guardian bulldog knife melee
site mid long short main heaven hell market garage hookah lobby link window tower spawn attacker
defender plant spike defuse rotate push peek flank smoke flash molly wall ult ultimate ability orb
round clutch ace headshot kill kills dead low one shot trade entry lurk eco buy save force
team enemy enemies sorry wait drop gun bomb timer nice good great bro guys okay yes right left behind
front back top door box corner ramp stairs rafters tree pillar cubby default retake
sense problem chance match game win lose last first next player pro rank ranked radiant immortal
diamond platinum stream chat thanks thank please first blood damage health shield armour armor
mix strat straight elbow close clear hold rush lineup setup utility recon dart wallbang spray timing
"""
_PAIRS = (("ph", "f"), ("w", "v"), ("ck", "k"), ("c", "k"), ("q", "k"), ("z", "j"), ("x", "ks"),
          ("th", "t"), ("dh", "d"), ("ai", "i"), ("au", "o"), ("aa", "a"), ("ee", "i"), ("oo", "u"),
          ("y", "i"))
# Hindi spellings of game words whose vowels no rule can mend.
ALIASES = {"chembar": "chamber", "laang": "long", "hevan": "heaven", "strait": "strat", "kloj": "close", "aalbo": "elbow", "diphyooz": "defuse",
           "diphyooj": "defuse"}


def _key(word: str, english: bool = False) -> str:
    """A word's sound, spelled loosely, so a Hindi spelling of an English word and
    the English spelling meet: plaant / plant, spaaik / spike, shaut / shot. The
    silent e is dropped from the English side only: on the Hindi side a final e is
    said (मैने maine is not "main")."""
    k = re.sub(r"[^a-z]", "", word.lower())
    if english and len(k) > 3 and k.endswith("e"):
        k = k[:-1]
    for x, y in _PAIRS:
        k = k.replace(x, y)
    return re.sub(r"(.)+", r"", k)


_ENGLISH: dict[str, str] = {}
for _w in ENGLISH.split():
    _ENGLISH.setdefault(_key(_w, english=True), _w)


def _aksharas(word: str) -> list[dict]:
    """A Devanagari word as consonant/vowel units: {"c": consonant, "v": vowel or
    None for the inherent a, "halant": bool, "nasal": str}."""
    out: list[dict] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in CONSONANTS:
            if i + 1 < len(word) and word[i + 1] == NUKTA:
                ch = NUKTA_FORMS.get(ch, ch)
                i += 1
            out.append({"c": CONSONANTS[ch], "v": None, "halant": False, "nasal": ""})
        elif ch == NUKTA:
            pass
        elif ch in MATRAS and out and out[-1]["c"] is not None and out[-1]["v"] is None:
            out[-1]["v"] = MATRAS[ch]
        elif ch == HALANT and out:
            out[-1]["halant"] = True
        elif ch in VOWELS:
            out.append({"c": None, "v": VOWELS[ch], "halant": False, "nasal": ""})
        elif ch in (ANUSVARA, CANDRA) and out:
            out[-1]["nasal"] = "n"
        elif ch == VISARGA and out:
            out[-1]["nasal"] = "h"
        elif ch in DIGITS:
            out.append({"c": None, "v": DIGITS[ch], "halant": False, "nasal": "", "raw": True})
        i += 1
    return out


def _word(word: str) -> str:
    units = _aksharas(word)
    if not units:
        return ""
    # Which inherent a's are said: not after a halant, not at the end of a word of
    # more than one letter, and not between a vowel and a consonant with a vowel
    # (Hindi's schwa deletion, right to left: करना karna, समझना samajhna).
    said = [u["c"] is not None and u["v"] is None and not u["halant"] for u in units]
    if len(units) > 1 and said[-1]:
        said[-1] = False
    for k in range(len(units) - 2, 0, -1):
        if not said[k] or units[k]["nasal"]:
            continue
        before = units[k - 1]
        after = units[k + 1]
        vowel_before = before["v"] is not None or said[k - 1]
        vowel_after = after["c"] is not None and (after["v"] is not None or said[k + 1])
        if vowel_before and vowel_after:
            said[k] = False
    parts = []
    for k, u in enumerate(units):
        if u.get("raw"):
            parts.append(u["v"])
            continue
        v = u["v"] if u["v"] is not None else ("a" if said[k] else "")
        nasal = u["nasal"]
        if nasal == "n" and k + 1 < len(units) and units[k + 1]["c"] in ("p", "b", "bh", "m", "ph"):
            nasal = "m"
        parts.append((u["c"] or "") + v + nasal)
    out = "".join(parts)
    # Chat spelling: a final long vowel is written short (kya, jaldi, tu), and a
    # long aa before another vowel too (bhaai -> bhai).
    out = re.sub(r"aa$", "a", out)
    out = re.sub(r"ee$", "i", out)
    out = re.sub(r"oo$", "u", out)
    out = re.sub(r"een$", "in", out)
    out = out.replace("nn", "n")             # मैंने: the nasal and the n are one sound
    out = re.sub(r"aa(?=[ieuo])", "a", out)
    out = out.replace("eeen", "een")
    return ALIASES.get(out) or _ENGLISH.get(_key(out)) or out


_TOKEN = re.compile(r"[ऀ-ॿ]+|[^ऀ-ॿ]+")


def romanize(text: str) -> str:
    """The text with every Devanagari word written in Latin letters; everything
    else -- English, numbers, punctuation -- as it was. Sentence starts are capitals."""
    if not text or not DEVANAGARI.search(text):
        return text or ""
    text = text.replace("।", ".").replace("॥", ".")
    out = []
    for tok in _TOKEN.findall(text):
        if DEVANAGARI.match(tok):
            out.append(_word(tok))
        else:
            out.append(tok)
    s = "".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)


def has_devanagari(text: str) -> bool:
    return bool(text and DEVANAGARI.search(text))
