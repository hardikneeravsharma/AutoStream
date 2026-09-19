"""Every part the reel maker can put in a shot, and the knobs that make them differ.

WHY THIS IS GENERATED AND NOT TYPED OUT
    A drawer of a hundred hand-written filter strings is a hundred things to
    verify and a hundred chances for one of them to silently do nothing. It is
    also the wrong shape: a punch at 12% over 0.35 s and a punch at 20% over
    0.18 s are not two effects, they are one effect keyed twice -- which is
    exactly how an editor works. So a family owns the filter, and its VARIANTS
    own the numbers.

    The renderer never sees a variant id. It looks the id up, takes `base` and
    `knobs`, and builds the family's filter with those numbers. A part added
    here needs no change in the renderer as long as its family already exists.

WHY THE NAMES MATTER
    Nobody picks an edit from `k01/0.20/0.18`. Every variant is named for what
    it does to the picture -- Hard punch, Slow settle, Creep -- because the
    Parts Bin is browsed by watching and read by name, and a hundred cards
    called "Zoom punch 7" is a worse drawer than twelve called nothing at all.

WHAT IS HONESTLY THIN
    Some drawers have more room than others. There are a great many ways to
    move a camera and only so many ways to end a reel, so `hero`, `intro` and
    `outro` reach their hundred on narrower ground than `kill` or `camera` do.
    That is a real difference and the blurbs say which axis is being varied
    rather than pretending each is a new idea.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Part:
    id: str
    kind: str
    label: str
    blurb: str
    # Which family's filter draws this, and with what numbers. A hand-written
    # part is its own base and carries the family's defaults.
    base: str = ""
    knobs: tuple[tuple[str, float], ...] = ()

    @property
    def family(self) -> str:
        return self.base or self.id

    def knob(self, name: str, default: float) -> float:
        for k, v in self.knobs:
            if k == name:
                return float(v)
        return default


# --------------------------------------------------------------- the families
#
# (base id, suffix, label, blurb, {knob: value}) -- one row per variant. The
# base row itself lives in studio.PARTS and keeps its own id, so a project made
# before this existed still resolves.

# How hard, and how long it takes to let go. Measured against the reference
# edits' own punches: their zooms sit between 6 and 22 per cent and settle
# between a fifth of a second and two thirds.
PUNCH = [
    ("soft", "Soft punch", "Barely there -- 6% closer, settling slowly.", {"amt": 0.06, "fall": 0.50}),
    ("mid", "Punch", "The usual: 12% closer over a third of a second.", {"amt": 0.12, "fall": 0.35}),
    ("hard", "Hard punch", "20% closer and gone in a fifth of a second.", {"amt": 0.20, "fall": 0.20}),
    ("snap", "Snap punch", "As deep as it gets, released almost at once.", {"amt": 0.22, "fall": 0.14}),
    ("settle", "Slow settle", "12% closer, taking two thirds of a second to let go.", {"amt": 0.12, "fall": 0.66}),
    ("creep", "Creep", "8% closer and it never quite leaves the shot.", {"amt": 0.08, "fall": 0.90}),
]

SHAKE = [
    ("soft", "Soft shake", "A tremor rather than a hit.", {"amp": 0.35, "fall": 0.30, "freq": 54.0}),
    ("mid", "Shake", "The frame rattles for under half a second.", {"amp": 0.70, "fall": 0.45, "freq": 70.0}),
    ("hard", "Hard shake", "A real knock, over quickly.", {"amp": 1.00, "fall": 0.28, "freq": 88.0}),
    ("long", "Rolling shake", "Rattles on for most of a second, fading out.", {"amp": 0.55, "fall": 0.85, "freq": 62.0}),
    ("fast", "Buzz", "High and tight, like a hit landing on metal.", {"amp": 0.45, "fall": 0.22, "freq": 120.0}),
    ("slow", "Lurch", "Slow and heavy, two or three swings.", {"amp": 0.85, "fall": 0.55, "freq": 34.0}),
]

FLASH = [
    ("thin", "Thin flash", "A single frame lifts, nothing more.", {"amt": 0.30, "fall": 0.06}),
    ("mid", "Flash", "One or two frames blow out to white.", {"amt": 0.55, "fall": 0.12}),
    ("wide", "Wide flash", "The whole frame whites out and comes back.", {"amt": 0.85, "fall": 0.22}),
    ("bloom", "Flash bloom", "Blows out and takes a third of a second to recover.", {"amt": 0.70, "fall": 0.34}),
    ("double", "Double flash", "Two lifts, a few frames apart.", {"amt": 0.50, "fall": 0.30}),
    ("dim", "Dim flash", "Barely a lift at all.", {"amt": 0.18, "fall": 0.10}),
]

BLUR = [
    ("soft", "Soft blur snap", "Goes a little soft and comes back.", {"r": 3.0, "dur": 0.18}),
    ("mid", "Blur snap", "Goes soft on the kill and snaps back sharp.", {"r": 6.0, "dur": 0.25}),
    ("hard", "Smear", "Heavily soft for a moment.", {"r": 12.0, "dur": 0.20}),
    ("long", "Held blur", "Soft for half a second before it clears.", {"r": 7.0, "dur": 0.50}),
    ("breath", "Breath blur", "Softens and clears over a whole second.", {"r": 5.0, "dur": 1.00}),
]

SPLIT = [
    ("thin", "Hair split", "Colour separates by a couple of pixels.", {"px": 4.0, "dur": 0.12}),
    ("mid", "RGB split", "Red and blue tear apart for a few frames.", {"px": 9.0, "dur": 0.18}),
    ("wide", "Wide split", "The channels tear right apart.", {"px": 18.0, "dur": 0.15}),
    ("long", "Held split", "Torn for a third of a second.", {"px": 11.0, "dur": 0.33}),
    ("creep", "Creeping split", "The tear opens over a quarter second.", {"px": 13.0, "dur": 0.26}),
]

VIGNETTE = [
    ("soft", "Soft vignette pulse", "The edges shade in gently.", {"amt": 0.35, "fall": 0.55}),
    ("mid", "Vignette pulse", "The edges darken hard on the kill.", {"amt": 0.60, "fall": 0.40}),
    ("hard", "Tunnel", "The frame closes right down and opens again.", {"amt": 0.95, "fall": 0.35}),
    ("slow", "Slow close", "The edges shade in and take their time leaving.", {"amt": 0.55, "fall": 0.85}),
    ("blink", "Vignette blink", "Closes and opens again in a blink.", {"amt": 0.75, "fall": 0.18}),
]

SAT = [
    ("soft", "Colour lift", "A little colour arrives with the kill.", {"from": 0.70, "to": 1.20, "fall": 0.60}),
    ("mid", "Saturation pop", "Muted colour until the kill, then it floods in.", {"from": 0.40, "to": 1.45, "fall": 0.60}),
    ("hard", "Colour slam", "Grey to full colour in one frame.", {"from": 0.10, "to": 1.70, "fall": 0.45}),
    ("drain", "Colour drain", "Full colour until the kill, then the colour goes.", {"from": 1.30, "to": 0.45, "fall": 0.70}),
    ("slow", "Slow bloom", "Colour arrives over a second.", {"from": 0.55, "to": 1.30, "fall": 1.00}),
]

TILT = [
    ("soft", "Soft tilt", "A small vertical nudge.", {"amp": 0.45, "fall": 0.30}),
    ("mid", "Tilt shake", "Rattles up and down only, not side to side.", {"amp": 0.85, "fall": 0.40}),
    ("hard", "Stomp", "One heavy vertical hit.", {"amp": 1.20, "fall": 0.25}),
    ("twice", "Double stomp", "Two vertical hits, the second smaller.", {"amp": 1.00, "fall": 0.55}),
    ("long", "Rolling stomp", "Rides up and down for most of a second.", {"amp": 0.60, "fall": 0.80}),
]

ROT = [
    ("soft", "Soft kick", "Half a degree, righted at once.", {"rad": 0.010, "fall": 0.28}),
    ("mid", "Rotation kick", "The frame knocks a degree or so and rights itself.", {"rad": 0.026, "fall": 0.35}),
    ("hard", "Dutch kick", "Two and a half degrees, held a moment.", {"rad": 0.045, "fall": 0.50}),
    ("back", "Counter kick", "Knocks the other way and rights itself.", {"rad": -0.026, "fall": 0.35}),
    ("slow", "Slow right", "A degree, taking most of a second to settle.", {"rad": 0.022, "fall": 0.80}),
]

ECHO = [
    ("short", "Short echo", "Movement smears behind itself briefly.", {"decay": 0.80, "dur": 0.20}),
    ("mid", "Echo trail", "Bright movement smears behind itself for a moment.", {"decay": 0.88, "dur": 0.35}),
    ("long", "Long echo", "Trails hang on for half a second.", {"decay": 0.93, "dur": 0.55}),
    ("faint", "Faint echo", "The barest smear, gone at once.", {"decay": 0.70, "dur": 0.15}),
    ("hold", "Held echo", "Trails stay up for the best part of a second.", {"decay": 0.95, "dur": 0.75}),
]

BLOOM = [
    ("soft", "Soft bloom", "Highlights warm and swell a little.", {"lift": 0.60, "dur": 0.22}),
    ("mid", "Highlight bloom", "Bright parts bloom and glow on the kill.", {"lift": 0.68, "dur": 0.30}),
    ("hard", "Blowout", "Highlights bloom right out.", {"lift": 0.80, "dur": 0.40}),
    ("slow", "Slow bloom", "Highlights swell and take their time.", {"lift": 0.66, "dur": 0.60}),
    ("blink", "Bloom blink", "One bright pulse and out.", {"lift": 0.78, "dur": 0.14}),
]

CRUNCH = [
    ("soft", "Soft crunch", "Contrast firms up for a moment.", {"con": 1.20, "sat": 1.08, "dur": 0.30}),
    ("mid", "Contrast crunch", "Blacks crush and colour hardens on the kill.", {"con": 1.45, "sat": 1.20, "dur": 0.30}),
    ("hard", "Slam crunch", "Hard blacks, hard colour, gone in a blink.", {"con": 1.80, "sat": 1.35, "dur": 0.18}),
    ("held", "Held crunch", "Hard contrast for most of a second.", {"con": 1.40, "sat": 1.15, "dur": 0.70}),
    ("flat", "Flatten", "Contrast drops away instead of hardening.", {"con": 0.72, "sat": 0.85, "dur": 0.30}),
]

WASH = [
    ("red", "Red hit", "A red wash flashes across the frame.", {"hue": 0.0, "alpha": 0.30, "dur": 0.15}),
    ("white", "White hit", "A pale wash across the frame.", {"hue": -1.0, "alpha": 0.24, "dur": 0.12}),
    ("purple", "Violet hit", "A violet wash, Valorant's own.", {"hue": 280.0, "alpha": 0.30, "dur": 0.15}),
    ("gold", "Gold hit", "A warm gold wash.", {"hue": 40.0, "alpha": 0.28, "dur": 0.16}),
    ("cyan", "Cyan hit", "A cold wash.", {"hue": 185.0, "alpha": 0.26, "dur": 0.15}),
    ("green", "Toxic hit", "A sick green wash.", {"hue": 110.0, "alpha": 0.26, "dur": 0.15}),
    ("deep", "Deep red hit", "A heavier red, held a moment longer.", {"hue": 0.0, "alpha": 0.42, "dur": 0.24}),
]

FLICKER = [
    ("soft", "Soft flicker", "Brightness wavers for a moment.", {"amt": 0.20, "dur": 0.20, "period": 6.0}),
    ("mid", "Flicker", "Brightness strobes for a quarter second.", {"amt": 0.35, "dur": 0.25, "period": 4.0}),
    ("hard", "Strobe", "Hard on-off strobing.", {"amt": 0.60, "dur": 0.30, "period": 2.0}),
    ("fast", "Fast flicker", "A very quick stutter of light.", {"amt": 0.30, "dur": 0.15, "period": 2.0}),
    ("long", "Long strobe", "Strobes for most of a second.", {"amt": 0.45, "dur": 0.70, "period": 4.0}),
]

INVERT = [
    ("one", "Single negative", "A single negative frame.", {"dur": 0.05}),
    ("two", "Negative blink", "Two or three negative frames.", {"dur": 0.10}),
    ("long", "Negative hold", "Inverted for a fifth of a second.", {"dur": 0.20}),
    ("flash", "Negative flash", "Inverts and returns inside two frames.", {"dur": 0.07}),
]

RELEASE = [
    ("soft", "Soft release", "Held 8% close, eased off through the kill.", {"amt": 0.08, "rise": 0.45}),
    ("mid", "Punch out", "Held close through the run-up, released on the kill.", {"amt": 0.12, "rise": 0.30}),
    ("hard", "Snap out", "Held deep and dropped the instant the kill lands.", {"amt": 0.20, "rise": 0.16}),
    ("slow", "Slow release", "Held close and let go over most of a second.", {"amt": 0.14, "rise": 0.80}),
    ("deep", "Deep release", "Held very close, then dropped.", {"amt": 0.26, "rise": 0.35}),
]

ZBLUR = [
    ("soft", "Soft zoom blur", "Punches in through a light haze.", {"sigma": 8.0, "dur": 0.08, "amt": 0.12}),
    ("mid", "Zoom blur hit", "Punches in through a blur that clears at once.", {"sigma": 14.0, "dur": 0.10, "amt": 0.18}),
    ("hard", "Warp hit", "A heavy blur and a deep punch, both gone in three frames.", {"sigma": 22.0, "dur": 0.07, "amt": 0.26}),
    ("long", "Held warp", "The blur clears over a third of a second.", {"sigma": 16.0, "dur": 0.30, "amt": 0.16}),
]

KILL_FAMILIES = {
    "k01": PUNCH, "k02": SHAKE, "k03": FLASH, "k06": SPLIT, "k07": SAT,
    "k08": WASH, "k11": CRUNCH, "k12": INVERT, "k14": BLUR, "k15": VIGNETTE,
    "k16": FLICKER, "k17": RELEASE, "k18": ECHO, "k19": ROT, "k20": BLOOM,
    "k21": ZBLUR, "k22": TILT,
}

# ----------------------------------------------------------------- transitions
#
# Every one of these is an xfade preset, so a variant is the preset plus how
# long it runs. Checked against the shipped ffmpeg before being offered.
XFADES = [
    ("fade", "Crossfade", "The two shots blend through each other."),
    ("fadewhite", "White flash", "The cut hides inside white."),
    ("fadeblack", "Dip to black", "Fades out to black and back up."),
    ("fadegrays", "Colour drain", "Drains to grey through the cut and back."),
    ("zoomin", "Zoom-through", "The first shot punches in and the next emerges."),
    ("hblur", "Whip blur", "A horizontal smear carries the cut."),
    ("dissolve", "Grain dissolve", "The shots trade places pixel by pixel."),
    ("pixelize", "Pixel dissolve", "Breaks into blocks and rebuilds."),
    ("radial", "Radial sweep", "Revealed by a clock-hand sweep."),
    ("circleopen", "Iris open", "Opens from a circle in the centre."),
    ("circleclose", "Iris close", "Closes to a circle and opens on the next."),
    ("circlecrop", "Circle crop", "The frame shrinks to a disc and back."),
    ("rectcrop", "Box crop", "The frame shrinks to a box and back."),
    ("distance", "Distance", "The shots pull apart in colour and rejoin."),
    ("wipeleft", "Wipe left", "A hard edge crosses right to left."),
    ("wiperight", "Wipe right", "A hard edge crosses left to right."),
    ("wipeup", "Wipe up", "A hard edge climbs the frame."),
    ("wipedown", "Wipe down", "A hard edge falls down the frame."),
    ("slideleft", "Push left", "The next shot shoves the last off to the left."),
    ("slideright", "Push right", "The next shot shoves the last off to the right."),
    ("slideup", "Push up", "The next shot shoves the last upward."),
    ("slidedown", "Push down", "The next shot shoves the last downward."),
    ("smoothleft", "Soft wipe left", "A feathered edge wipes leftward."),
    ("smoothright", "Soft wipe right", "A feathered edge wipes rightward."),
    ("smoothup", "Soft wipe up", "A feathered edge wipes upward."),
    ("smoothdown", "Soft wipe down", "A feathered edge wipes downward."),
    ("diagtl", "Diagonal wipe", "Corner to corner, top left first."),
    ("diagtr", "Diagonal wipe back", "Corner to corner, top right first."),
    ("diagbl", "Diagonal rise", "Corner to corner, bottom left first."),
    ("diagbr", "Diagonal fall", "Corner to corner, bottom right first."),
    ("hlslice", "Slice across", "Bands slide the next shot in from the left."),
    ("hrslice", "Slice back", "Bands slide the next shot in from the right."),
    ("vuslice", "Slice up", "Bands slide the next shot up."),
    ("vdslice", "Slice down", "Bands slide the next shot down."),
    ("squeezeh", "Squeeze", "The last shot squashes out sideways."),
    ("squeezev", "Squeeze flat", "The last shot squashes out vertically."),
    ("coverleft", "Cover left", "The next shot slides in over the last."),
    ("coverright", "Cover right", "The next shot slides in from the right."),
    ("coverup", "Cover up", "The next shot slides up over the last."),
    ("coverdown", "Cover down", "The next shot drops over the last."),
    ("revealleft", "Reveal left", "The last shot slides off to the left."),
    ("revealright", "Reveal right", "The last shot slides off to the right."),
    ("revealup", "Reveal up", "The last shot slides off upward."),
    ("revealdown", "Reveal down", "The last shot slides off downward."),
    ("horzopen", "Open across", "The frame parts left and right."),
    ("horzclose", "Close across", "The frame closes from left and right."),
    ("vertopen", "Open apart", "The frame parts up and down."),
    ("vertclose", "Close together", "The frame closes from top and bottom."),
    ("fadefast", "Fast fade", "A blend weighted to the front."),
    ("fadeslow", "Slow fade", "A blend weighted to the back."),
]
# How long a cut runs. Short reads as a cut, long reads as an effect.
CUT_LENGTHS = [("q", "quick", 0.2), ("", "", 0.32), ("s", "slow", 0.55)]

# --------------------------------------------------------------------- camera
CAMERA = [
    ("c01", "push", "Push in", "Drifts steadily closer.", "amt", [
        ("hair", "a hair", 0.04), ("soft", "a touch", 0.07), ("", "", 0.12),
        ("far", "a long way", 0.20), ("deep", "deep", 0.30)]),
    ("c05", "pull", "Pull out", "Starts close and eases back.", "amt", [
        ("hair", "a hair", 0.05), ("soft", "a touch", 0.08), ("", "", 0.14),
        ("far", "a long way", 0.22), ("deep", "deep", 0.32)]),
    ("c08", "breathe", "Breathing zoom", "Eases in and out again.", "amt", [
        ("hair", "barely", 0.03), ("soft", "shallow", 0.05), ("", "", 0.07),
        ("deep", "deep", 0.12), ("swell", "a big swell", 0.18)]),
    ("c04", "bounce", "Beat bounce", "Pulses closer on every beat.", "amt", [
        ("hair", "barely", 0.02), ("soft", "gentle", 0.04), ("", "", 0.06),
        ("hard", "hard", 0.10), ("slam", "slamming", 0.15)]),
    ("c03", "drift", "Handheld drift", "A gentle organic sway.", "amp", [
        ("still", "almost still", 0.20), ("soft", "barely moving", 0.35), ("", "", 0.60),
        ("loose", "loose", 1.00), ("wild", "wild", 1.40)]),
    ("c06", "roll", "Roll drift", "Rotates slowly across the shot.", "rad", [
        ("hair", "half a degree", 0.009), ("soft", "a degree", 0.018), ("", "", 0.030),
        ("far", "three degrees", 0.052), ("deep", "five degrees", 0.087)]),
    ("c07", "pan", "Parallax pan", "Drifts sideways across the scene.", "amp", [
        ("hair", "a little", 0.25), ("soft", "slight", 0.45), ("", "", 0.90),
        ("far", "right across", 1.30), ("sweep", "a full sweep", 1.70)]),
]
CAMERA_DIRS = [("", "", 1.0), ("back", "the other way", -1.0)]
# HOW A MOVE GETS WHERE IT IS GOING. The same push feels different arriving:
# even is a dolly, slow-in creeps then commits, slow-out leaves at once and
# settles. Only the moves that travel across a whole shot take a curve --
# a bounce and a sway are already shaped by the beat and by the noise.
CAMERA_CURVES = [("", "", 0.0), ("in", "easing in", 1.0), ("out", "easing out", 2.0)]
CAMERA_CURVED = {"push", "pull", "breathe"}

# ---------------------------------------------------------------------- grade
#
# A grade is saturation, contrast, brightness and a hue push. Generating them
# over a hue wheel gives a real spread of looks from one filter, and the names
# say the colour rather than the angle.
TINTS = [
    ("amber", "Amber", 35.0), ("gold", "Gold", 48.0), ("sand", "Sand", 60.0),
    ("lime", "Lime", 85.0), ("jade", "Jade", 130.0), ("sea", "Sea", 160.0),
    ("teal", "Teal", 180.0), ("ice", "Ice", 200.0), ("steel", "Steel", 215.0),
    ("cobalt", "Cobalt", 228.0), ("indigo", "Indigo", 250.0), ("violet", "Violet", 275.0),
    ("orchid", "Orchid", 295.0), ("magenta", "Magenta", 315.0), ("rose", "Rose", 340.0),
    ("ember", "Ember", 10.0), ("rust", "Rust", 22.0), ("brass", "Brass", 52.0),
    ("moss", "Moss", 105.0), ("mint", "Mint", 150.0), ("cyan", "Cyan", 190.0),
    ("slate", "Slate", 208.0), ("denim", "Denim", 238.0), ("plum", "Plum", 288.0),
    ("fuchsia", "Fuchsia", 322.0), ("blush", "Blush", 350.0),
]
GRADE_WEIGHTS = [
    ("wash", "wash", 0.30, 0.95, 1.02),      # (suffix, word, tint strength, sat, contrast)
    ("", "", 0.55, 1.12, 1.06),
    ("deep", "deep", 0.85, 1.28, 1.14),
    ("mono", "mono", 0.45, 0.25, 1.18),
]

# -------------------------------------------------------------------- overlay
OVERLAY = [
    ("o04", "grain", "Film grain", "Moving grain over the whole reel.", "amt",
     [("fine", "fine", 6.0), ("", "", 10.0), ("heavy", "heavy", 18.0), ("coarse", "coarse", 26.0)]),
    ("o05", "scan", "Scanlines", "Fine horizontal lines, like an old monitor.", "pitch",
     [("fine", "fine", 1.0), ("", "", 2.0), ("wide", "wide", 3.0), ("crt", "like a CRT", 4.0)]),
    ("o08", "fringe", "Chromatic edges", "A hair of colour fringing.", "px",
     [("hair", "a hair", 1.0), ("", "", 2.0), ("wide", "wide", 4.0)]),
    ("o01", "bars", "Cinematic bars", "Black bars top and bottom.", "h",
     [("thin", "thin", 0.08), ("", "", 0.125), ("wide", "wide", 0.16), ("scope", "scope", 0.20)]),
]

# ---------------------------------------------------------- intro / outro / hero
FADES = [("q", "quick", 0.35), ("", "", 0.7), ("s", "slow", 1.2), ("vs", "very slow", 2.0)]
FADE_COLOURS = [("black", "black", "black"), ("white", "white", "white"),
                ("grey", "grey", "gray"), ("violet", "violet", "0x2a1840"),
                ("navy", "navy", "0x0d1830"), ("red", "red", "0x3a0f12")]
HERO = [
    ("h01", "double", "Double punch", "Two punches close together.", "gap",
     [("tight", "a tenth apart", 0.10), ("", "", 0.16), ("wide", "a quarter apart", 0.25)]),
    ("h02", "freeze", "Freeze and push in", "Time stops while the camera pushes in.", "hold",
     [("short", "briefly", 0.35), ("", "", 0.6), ("long", "a long beat", 1.0)]),
    ("h03", "spot", "Spotlight", "Everything but the centre drops away.", "amt",
     [("soft", "softly", 0.6), ("", "", 0.9), ("hard", "hard", 1.2)]),
    ("h05", "slam", "Text slam", "The caption slams in and settles.", "scale",
     [("soft", "gently", 1.4), ("", "", 1.9), ("hard", "hard", 2.6)]),
]


def _name(label: str, word: str) -> str:
    return f"{label} ({word})" if word else label


def variants(kinds: dict[str, str]) -> list[Part]:
    """Every generated part. `kinds` maps a base id to its drawer."""
    out: list[Part] = []

    def add(pid, kind, label, blurb, base, knobs):
        out.append(Part(pid, kind, label, blurb, base, tuple(sorted(knobs.items()))))

    # -- on the kill ------------------------------------------------------
    for base, rows in KILL_FAMILIES.items():
        for suffix, label, blurb, knobs in rows:
            pid = f"{base}{suffix}"
            if pid == base:
                continue
            add(pid, "kill", label, blurb, base, knobs)

    # -- between shots ----------------------------------------------------
    for x, (preset, label, blurb) in enumerate(XFADES):
        for suffix, word, secs in CUT_LENGTHS:
            add(f"x{x:02d}{suffix}", "transition", _name(label, word), blurb,
                "xfade", {"secs": secs, "preset": float(x)})

    # -- camera -----------------------------------------------------------
    for base, fam, label, blurb, knob, rows in CAMERA:
        for suffix, word, val in rows:
            for dsuffix, dword, sign in CAMERA_DIRS:
                if sign < 0 and fam not in ("pan", "roll", "drift"):
                    continue                      # only the sideways ones reverse
                curves = CAMERA_CURVES if fam in CAMERA_CURVED else CAMERA_CURVES[:1]
                for csuffix, cword, curve in curves:
                    pid = f"{base}{suffix}{dsuffix}{csuffix}"
                    if pid == base:
                        continue
                    words = " ".join(w for w in (word, dword, cword) if w)
                    add(pid, "camera", _name(label, words), blurb, base,
                        {knob: val * sign, "curve": curve})

    # -- colour -----------------------------------------------------------
    for tint, tname, hue in TINTS:
        for suffix, word, strength, sat, con in GRADE_WEIGHTS:
            add(f"gt_{tint}{'_' + suffix if suffix else ''}", "grade",
                _name(tname, word),
                f"Pushes the whole picture toward {tname.lower()}"
                + (" and drains the rest of the colour." if suffix == "mono" else "."),
                "tint", {"hue": hue, "strength": strength, "sat": sat, "con": con})

    # -- over the reel ----------------------------------------------------
    for base, fam, label, blurb, knob, rows in OVERLAY:
        for suffix, word, val in rows:
            pid = f"{base}{suffix}"
            if pid == base:
                continue
            add(pid, "overlay", _name(label, word), blurb, base, {knob: val})

    # -- the big moment ---------------------------------------------------
    for base, fam, label, blurb, knob, rows in HERO:
        for suffix, word, val in rows:
            pid = f"{base}{suffix}"
            if pid == base:
                continue
            add(pid, "hero", _name(label, word), blurb, base, {knob: val})

    # -- opening and ending ------------------------------------------------
    for csuffix, cword, colour in FADE_COLOURS:
        for suffix, word, secs in FADES:
            add(f"if_{csuffix}{'_' + suffix if suffix else ''}", "intro",
                _name(f"Fade up from {cword}", word),
                f"{cword.capitalize()} resolves into the first shot.",
                "fade_in", {"secs": secs, "colour": float(FADE_COLOURS.index((csuffix, cword, colour)))})
            add(f"ef_{csuffix}{'_' + suffix if suffix else ''}", "outro",
                _name(f"Fade to {cword}", word),
                f"The last shot fades out to {cword}.",
                "fade_out", {"secs": secs, "colour": float(FADE_COLOURS.index((csuffix, cword, colour)))})
    return out


FADE_HEX = [c[2] for c in FADE_COLOURS]
XFADE_NAMES = [x[0] for x in XFADES]


# ------------------------------------------------------------------ favourites
#
# WHERE THESE LIVE. In the config directory, not the clips folder: a person
# empties the clips folder to free a drive, and the parts they like are not
# footage. One flat list of ids, because a favourite is a favourite whichever
# drawer it came from and the drawer is already on the part.

FAV_FILE = "favourite_parts.json"


def load_favourites(config_dir) -> list[str]:
    """The ids marked as favourites, in the order they were marked."""
    import json
    from pathlib import Path

    p = Path(config_dir) / FAV_FILE
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(got, list):
        return []
    return [str(x) for x in got if isinstance(x, str)][:2000]


def save_favourites(config_dir, ids) -> list[str]:
    """Write the list back, deduped and order kept. -> what was written."""
    import json
    from pathlib import Path

    out = list(dict.fromkeys(str(x) for x in ids if isinstance(x, str)))[:2000]
    p = Path(config_dir) / FAV_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    # Written whole and renamed, so a crash mid-write cannot leave a file that
    # parses as an empty list and silently forgets every favourite.
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    tmp.replace(p)
    return out
