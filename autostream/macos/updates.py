"""The in-app updater, on a Mac: an honest "not from here".

Every GitHub release carries a Windows installer and a Windows zip. The
updater's job is to download one, verify it and run it -- all three of which
would be wrong on a Mac, and the second would cost 70 MB first. Until releases
carry a Mac build, the answer is a sentence, not a button.
"""
from __future__ import annotations

WHY = ("Updates are not offered from inside the Mac build yet: every release "
       "on GitHub is a Windows download. Pull the latest source and rebuild "
       "with scripts/macos/build.sh.")


def check(current: str) -> dict:
    """What update_check answers. The shape the Settings page already reads."""
    return {"ok": True, "checked": True, "available": False, "newer": False,
            "current": current, "why": WHY, "cached": False}


def refuse() -> dict:
    return {"error": WHY}
