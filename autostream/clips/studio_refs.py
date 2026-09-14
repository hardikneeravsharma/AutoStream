"""What popular FPS montage edits actually do, measured -- the ground the Studio's styles stand on.

26 edits between 137 thousand and 5.9 million views (25 Valorant, one Call of
Duty montage cut to the same kind of song), plus the reel v9 made on
this machine, downloaded once and measured frame by frame: cuts and white
flashes by frame difference and brightness, fades by the first and last half
second, beat alignment against each video's own detected tempo. Only the
numbers live here; no footage, no audio.

Close rather than exact. A fast camera flick can read as a cut, and tempo
detection can lock onto half-time -- which is why the styles use MEDIANS over
several edits, never one edit's figure.

`v9` is the reference reel from this machine, not a YouTube video.
"""
from __future__ import annotations

EDITS: list[dict] = [
    {"id": "JsTJ60BPTfQ", "title": "lalala 💜🔥", "channel": "Zishu", "views": 5946176, "cuts_per_min": 32.2, "median_shot": 0.92, "first_shot": 7.67, "flashes_per_min": 11.9, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.37, "cuts_on_halfbeat": 0.56, "dur": 106.3},
    {"id": "c1VjTbzcEds", "title": "No Lie 🙅‍♂️🔥 (Valorant Montage)", "channel": "Zishu", "views": 4475524, "cuts_per_min": 34.9, "median_shot": 1.05, "first_shot": 3.17, "flashes_per_min": 24.0, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.26, "cuts_on_halfbeat": 0.46, "dur": 105.0},
    {"id": "fAyUxeDzKlI", "title": "ENEMY 😈", "channel": "cjaiye", "views": 3481601, "cuts_per_min": 24.9, "median_shot": 1.6, "first_shot": 2.07, "flashes_per_min": 9.7, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.63, "cuts_on_halfbeat": 0.75, "dur": 142.4},
    {"id": "wlNmShwGaJY", "title": "Cold ❄️ (Valorant RADIANT Montage)", "channel": "tteuw", "views": 3142013, "cuts_per_min": 69.1, "median_shot": 0.6, "first_shot": 1.13, "flashes_per_min": 25.1, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.37, "cuts_on_halfbeat": 0.83, "dur": 133.8},
    {"id": "vQqU0F8vTOE", "title": "Beggin' 🙏🔥 (Valorant Montage)", "channel": "Zishu", "views": 2001142, "cuts_per_min": 23.4, "median_shot": 1.07, "first_shot": 9.07, "flashes_per_min": 17.7, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.59, "cuts_on_halfbeat": 0.76, "dur": 95.1},
    {"id": "H2N0eHGOi_w", "title": "Untouchable - Valorant Edit", "channel": "ClownY", "views": 1557129, "cuts_per_min": 30.2, "median_shot": 0.92, "first_shot": 1.8, "flashes_per_min": 20.1, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.33, "cuts_on_halfbeat": 1.0, "dur": 17.9},
    {"id": "8KKGT4JXPVY", "title": "Cold ❄️ (Valorant Montage)", "channel": "shawnnlol", "views": 1336716, "cuts_per_min": 21.4, "median_shot": 2.03, "first_shot": 5.3, "flashes_per_min": 11.3, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.29, "cuts_on_halfbeat": 0.53, "dur": 95.3},
    {"id": "8bQ-8ZnHG4A", "title": "moonlight valorant edit", "channel": "GRIZZ ♨️", "views": 1308146, "cuts_per_min": 19.1, "median_shot": 2.67, "first_shot": 3.97, "flashes_per_min": 35.0, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.67, "cuts_on_halfbeat": 0.67, "dur": 18.8},
    {"id": "oJDesm--wss", "title": "TELL EM - Valorant Edit", "channel": "Flintc", "views": 1206783, "cuts_per_min": 65.3, "median_shot": 0.63, "first_shot": 5.33, "flashes_per_min": 51.7, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.29, "cuts_on_halfbeat": 0.38, "dur": 22.1},
    {"id": "prevxQTdkGo", "title": "moonlight 🌙 - valorant edit", "channel": "verse", "views": 1043065, "cuts_per_min": 38.6, "median_shot": 0.9, "first_shot": 5.7, "flashes_per_min": 18.0, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.53, "cuts_on_halfbeat": 0.6, "dur": 23.3},
    {"id": "yBvW49SD20Y", "title": "Boy's a Liar 🤍", "channel": "cjaiye", "views": 969955, "cuts_per_min": 21.4, "median_shot": 2.12, "first_shot": 1.63, "flashes_per_min": 5.5, "fade_in": False, "fade_out": True, "cuts_on_beat": 0.13, "cuts_on_halfbeat": 0.34, "dur": 131.7},
    {"id": "xrgExBQyHBc", "title": "Young Girl A [Valorant Edit]", "channel": "SAYO", "views": 918971, "cuts_per_min": 45.4, "median_shot": 0.43, "first_shot": 4.3, "flashes_per_min": 69.5, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.18, "cuts_on_halfbeat": 0.47, "dur": 22.5},
    {"id": "DM3eKiZD3XE", "title": "Dancin 💃 (Valorant Montage)", "channel": "Ladiff", "views": 799081, "cuts_per_min": 29.4, "median_shot": 1.28, "first_shot": 3.23, "flashes_per_min": 25.2, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.14, "cuts_on_halfbeat": 0.22, "dur": 100.1},
    {"id": "qAlD8eNIfr8", "title": "No Lie 🙅‍♂️🔥 (Valorant Montage)", "channel": "Fluxx", "views": 781613, "cuts_per_min": 27.2, "median_shot": 1.3, "first_shot": 6.57, "flashes_per_min": 11.8, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.26, "cuts_on_halfbeat": 0.59, "dur": 101.7},
    {"id": "DrC9DxQ27lI", "title": "KAWAII  (◕‿◕✿)  - Valorant Edit ( + Project File)", "channel": "veltix", "views": 699812, "cuts_per_min": 25.4, "median_shot": 0.97, "first_shot": 8.63, "flashes_per_min": 22.2, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.5, "cuts_on_halfbeat": 0.88, "dur": 18.9},
    {"id": "66zl0-VoWbg", "title": "TIMELESS - Call of Duty Montage", "channel": "Kaiser", "views": 673646, "cuts_per_min": 48.3, "median_shot": 0.93, "first_shot": 1.63, "flashes_per_min": 40.6, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.15, "cuts_on_halfbeat": 0.35, "dur": 170.1},
    {"id": "-rkr4IpA3jM", "title": "BLOODPOP 🩸| Valorant edit", "channel": "Haruqie", "views": 475683, "cuts_per_min": 26.6, "median_shot": 1.0, "first_shot": 15.0, "flashes_per_min": 11.6, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.12, "cuts_on_halfbeat": 0.5, "dur": 36.1},
    {"id": "wZjYRJWKuM8", "title": "CLEANEST 𝑫𝑨𝑽𝑰𝑵𝑪𝑰 𝑹𝑬𝑺𝑶𝑳𝑽𝑬 VALORANT Edit | From The Start", "channel": "chae", "views": 453576, "cuts_per_min": 42.5, "median_shot": 0.83, "first_shot": 0.2, "flashes_per_min": 24.3, "fade_in": False, "fade_out": True, "cuts_on_beat": 0.5, "cuts_on_halfbeat": 0.57, "dur": 39.5},
    {"id": "RjCsmKbYY7g", "title": "Beyond / Valorant Edit", "channel": "快樂玻璃鞋", "views": 406468, "cuts_per_min": 17.3, "median_shot": 1.37, "first_shot": 11.13, "flashes_per_min": 1.3, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.27, "cuts_on_halfbeat": 0.81, "dur": 90.0},
    {"id": "Ro6MDXmB8uA", "title": "🍀ONE CHANCE | Valorant edit 4K", "channel": "Haruqie", "views": 398299, "cuts_per_min": 54.4, "median_shot": 0.53, "first_shot": 5.03, "flashes_per_min": 36.3, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.3, "cuts_on_halfbeat": 0.47, "dur": 33.1},
    {"id": "nqa8RP_R0cU", "title": "Levitating - Valorant Edit", "channel": "StrixISL", "views": 393286, "cuts_per_min": 58.3, "median_shot": 0.62, "first_shot": 2.43, "flashes_per_min": 78.7, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.3, "cuts_on_halfbeat": 0.42, "dur": 44.2},
    {"id": "0OvnyxlKLeQ", "title": "STEP BACK - Valorant Montage", "channel": "Defect", "views": 360478, "cuts_per_min": 54.3, "median_shot": 0.63, "first_shot": 1.0, "flashes_per_min": 22.1, "fade_in": False, "fade_out": False, "cuts_on_beat": 0.19, "cuts_on_halfbeat": 0.35, "dur": 125.0},
    {"id": "RmaACKww8do", "title": "AFTER DARK 🌑- Valorant Edit", "channel": "Mor0sis", "views": 295105, "cuts_per_min": 43.8, "median_shot": 0.88, "first_shot": 2.5, "flashes_per_min": 14.6, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.19, "cuts_on_halfbeat": 0.38, "dur": 28.7},
    {"id": "w7KxRynHTDw", "title": "GOAT's of Valorant - Omen x Chamber x Yoru Edit | Funk Criminal (Slowed & Reverb)", "channel": "Morningstar AEP", "views": 228381, "cuts_per_min": 36.1, "median_shot": 1.07, "first_shot": 0.03, "flashes_per_min": 0.0, "fade_in": False, "fade_out": True, "cuts_on_beat": 0.33, "cuts_on_halfbeat": 0.67, "dur": 15.0},
    {"id": "FEKdk-cPVmg", "title": "Timeless ⌛🔥(Valorant Montage)", "channel": "Zishu", "views": 148853, "cuts_per_min": 53.4, "median_shot": 0.63, "first_shot": 4.07, "flashes_per_min": 38.2, "fade_in": True, "fade_out": False, "cuts_on_beat": 0.21, "cuts_on_halfbeat": 0.39, "dur": 86.4},
    {"id": "nkAEXZE76II", "title": "Timeless ❤️ (Valorant Montage)", "channel": "Fluxx", "views": 137368, "cuts_per_min": 36.1, "median_shot": 1.0, "first_shot": 4.8, "flashes_per_min": 21.2, "fade_in": True, "fade_out": True, "cuts_on_beat": 0.38, "cuts_on_halfbeat": 0.55, "dur": 48.1},
    {"id": "v9", "title": "AUTO_REEL_v9", "channel": "AutoStream", "views": 0, "cuts_per_min": 32.3, "median_shot": 1.07, "first_shot": 5.8, "flashes_per_min": 4.6, "fade_in": False, "fade_out": True, "cuts_on_beat": 0.1, "cuts_on_halfbeat": 0.19, "dur": 39.0},
]

BY_ID = {e["id"]: e for e in EDITS}


def median(values: list[float]) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def summary(ids) -> dict:
    """The medians a style is built from, over the edits it names."""
    got = [BY_ID[i] for i in ids if i in BY_ID]
    if not got:
        return {"edits": 0}
    return {
        "edits": len(got),
        "cuts_per_min": round(median([e["cuts_per_min"] for e in got]), 1),
        "flashes_per_min": round(median([e["flashes_per_min"] for e in got]), 1),
        "first_shot": round(median([e["first_shot"] for e in got]), 1),
        "median_shot": round(median([e["median_shot"] for e in got]), 2),
        "fade_in": round(sum(1 for e in got if e["fade_in"]) / len(got), 2),
        "fade_out": round(sum(1 for e in got if e["fade_out"]) / len(got), 2),
        "names": [e["title"] if e["id"] != "v9" else "reel v9" for e in got],
    }
