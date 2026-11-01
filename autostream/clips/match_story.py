"""The story of a match: how the score moved, and which rounds it turned on.

WHY THIS EXISTS
    The recap chose its moments by what the player did in them -- kills, labels,
    the microphone -- and ChatGPT, grading it as a summary of the MATCH, gave it
    5.5/10 for momentum: "it doesn't show how the score evolved, what happened at
    half-time, whether the match had streaks or comeback phases" (2026-11-01).
    The Bind match it was reviewing went 4-8 at the half, fell to 4-12 after six
    straight losses, won seven of the next eight to 11-12, and lost the last round.
    A recap of that match that never says so has missed the match.

    Everything here is arithmetic over who won each round, from the match record --
    the WHOLE match, not the rounds the recording happens to hold (it began at
    round 6 of that one). Nothing is inferred from the screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STREAK = 3          # rounds won in a row that count as a run
SWING = 3           # rounds of score difference a comeback or collapse must cover


@dataclass
class Story:
    """The arc of one match, for the player's team. Rounds are numbered from 1."""
    won: list[bool | None]                       # per round, in order
    half: int = 12                               # rounds in a half (Valorant 12, CS2 12)
    win_at: int = 13                             # rounds that win the match
    after: list[tuple[int, int]] = field(default_factory=list)    # score after each round

    def __post_init__(self):
        a = b = 0
        self.after = []
        for w in self.won:
            if w is True:
                a += 1
            elif w is False:
                b += 1
            self.after.append((a, b))

    @property
    def rounds(self) -> int:
        return len(self.won)

    @property
    def final(self) -> tuple[int, int]:
        return self.after[-1] if self.after else (0, 0)

    @property
    def half_score(self) -> tuple[int, int] | None:
        return self.after[self.half - 1] if len(self.after) >= self.half else None

    def before(self, n: int) -> tuple[int, int]:
        return self.after[n - 2] if n >= 2 else (0, 0)

    def runs(self) -> list[tuple[int, int, bool]]:
        """(first round, last round, won) of every run of STREAK or more by one side."""
        out, i = [], 0
        while i < len(self.won):
            j = i
            while j + 1 < len(self.won) and self.won[j + 1] == self.won[i] and self.won[i] is not None:
                j += 1
            if self.won[i] is not None and j - i + 1 >= STREAK:
                out.append((i + 1, j + 1, bool(self.won[i])))
            i = j + 1
        return out

    def swing(self) -> tuple[int, int, bool] | None:
        """The biggest turn in the match: (first round, last round, toward the player).

        A COMEBACK starts at least SWING rounds down and wins back at least SWING; a
        COLLAPSE gives back at least SWING from a lead of at least SWING. A 1-0 lead
        lost is not a collapse -- the first version of this called the Bind match's
        rounds 2-15 one, from 1-0, and missed the comeback that was the story.
        The Bind match: rounds 16-23, 4-11 to 11-12 -- seven of eight won."""
        diffs = [0] + [a - b for a, b in self.after]
        best = None
        for i in range(len(diffs)):
            for j in range(i + 1, len(diffs)):
                move = diffs[j] - diffs[i]
                behind = diffs[i] <= -SWING if move > 0 else diffs[i] >= SWING
                if abs(move) >= SWING and behind and (best is None or abs(move) > abs(best[0])):
                    best = (move, i + 1, j)
        if best is None:
            return None
        move, a, b = best
        return a, b, move > 0

    def importance(self, n: int) -> tuple[float, str]:
        """How much round `n` mattered to the match, 0..1, and why in a few words.

        The final round, match point and a round that changes the lead matter most;
        then the last round of the biggest swing, a round that ends a run, the rounds
        either side of half-time. Only the strongest reason is kept."""
        if not 1 <= n <= len(self.won):
            return 0.0, ""
        a, b = self.after[n - 1]
        pa, pb = self.before(n)
        reasons: list[tuple[float, str]] = []
        if n == len(self.won):
            reasons.append((1.0, "Final round"))
        if max(pa, pb) == self.win_at - 1 and n != len(self.won):
            reasons.append((0.8, "Match point"))
        if n > self.half * 2:
            reasons.append((0.75, "Overtime"))
        # The lead changes hands only through a tie -- a round moves the score by one --
        # so a round that breaks a tie is the one that decides who leads. Early in a
        # match that is ordinary (1-1 to 1-2); it weighs less than match point.
        if pa == pb and a != b and n > 1:
            reasons.append((0.45, "Goes ahead" if a > b else "Falls behind"))
        sw = self.swing()
        if sw and sw[1] == n:
            reasons.append((0.65, "The comeback" if sw[2] else "The collapse"))
        for first, last, won in self.runs():
            if n == last + 1:
                reasons.append((0.55, "Ends the streak" if not won else "Streak broken"))
        if n in (self.half, self.half + 1):
            reasons.append((0.4, "Half-time" if n == self.half else "Second half"))
        if not reasons:
            return 0.0, ""
        return max(reasons, key=lambda r: r[0])

    def must_show(self) -> list[int]:
        """Rounds a recap of this match should not leave out when it has their footage:
        the final round, and the end of the biggest swing (ChatGPT's coverage rule)."""
        out = [len(self.won)] if self.won else []
        sw = self.swing()
        if sw and sw[1] not in out:
            out.append(sw[1])
        return out

    def phase(self, n: int) -> int:
        """Which part of the match round `n` is in: 0 first half, 1 second, 2 overtime."""
        return 0 if n <= self.half else 1 if n <= self.half * 2 else 2

    def line(self) -> str:
        """The match in one sentence, for a title card or a description."""
        a, b = self.final
        bits = []
        hs = self.half_score
        if hs:
            bits.append(f"{hs[0]}-{hs[1]} at the half")
        sw = self.swing()
        if sw:
            lo, hi, up = sw
            ba, bb = self.before(lo)
            ea, eb = self.after[hi - 1]
            bits.append(f"{'came back' if up else 'fell back'} from {ba}-{bb} to {ea}-{eb}")
        verdict = "won" if a > b else "lost" if b > a else "drew"
        bits.append(f"{verdict} {a}-{b}")
        return ", ".join(bits)
