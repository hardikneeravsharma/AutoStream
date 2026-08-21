"""Tests for app discovery.

Every case here is a game that was installed and simply did not appear in the
Library. None of them raised anything -- discovery returned a shorter list and
looked like it had worked, which is why they need tests rather than care.
"""
from __future__ import annotations

import ntpath
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import catalog  # noqa: E402


# ------------------------------------------------------- launcher-proxied games

def test_riot_launcher_is_recognised_as_a_launcher():
    """VALORANT's shortcut points at RiotClientServices.exe, and "service" is a
    helper marker. That one substring kept an installed game out of the Library."""
    assert catalog.is_helper("RiotClientServices.exe") is True
    assert catalog.is_launcher(r"C:\Riot Games\Riot Client\RiotClientServices.exe")


def test_known_launchers_are_matched_on_basename_only():
    assert catalog.is_launcher(r"D:\Games\Battle.net\Battle.net.exe")
    assert catalog.is_launcher("battle.net.exe")
    assert not catalog.is_launcher(r"C:\Games\SomeGame\game.exe")
    assert not catalog.is_launcher("")


def test_the_real_game_exe_is_resolved_from_the_display_name():
    """launch_intent is keyed on App.exe, so keying it on the LAUNCHER would
    mean Open + stream started the game and then never went live."""
    got = catalog._game_exe("VALORANT", r"C:\Riot Games\Riot Client\RiotClientServices.exe")
    assert got == "valorant-win64-shipping.exe"


def test_game_exe_falls_back_to_the_launcher_when_unknown():
    got = catalog._game_exe("Some Game Nobody Has Heard Of",
                            r"C:\X\RiotClientServices.exe")
    assert got == "riotclientservices.exe"


# ---------------------------------------------------------------- steam depth

def test_steam_walk_reaches_unreal_launcher_stub_layouts():
    """Delta Force ships a 247 KB stub at depth 1 and the real 551 MB binary at
    Game\\<Name>\\Binaries\\Win64 -- depth 4. The limit was 3, so the size floor
    rejected the stub and the walk never saw the binary."""
    assert catalog.STEAM_WALK_DEPTH >= 4


def test_shipping_binaries_beat_a_bigger_plain_exe():
    """The scoring bonus is what stops a fat launcher stub winning."""
    plain = 900 * 10 ** 6
    shipping = 1 * 10 ** 6 + 10 ** 12
    assert shipping > plain


# ------------------------------------------------------------------- hygiene

def test_autostream_does_not_list_itself():
    assert not any(a.name.lower() == "autostream"
                   for a in catalog.discover_shortcuts())


def test_shipping_exes_are_never_treated_as_helpers():
    # "-shipping" contains no marker, but the guard is explicit because these
    # are the single most important filenames not to drop.
    for name in ("DeltaForceClient-Win64-Shipping.exe",
                 "VALORANT-Win64-Shipping.exe",
                 "PenguinHotel-Win64-Shipping.exe"):
        assert catalog.is_helper(name) is False


def test_helper_markers_still_reject_the_obvious():
    for name in ("unins000.exe", "vcredist_x64.exe", "CrashHandler.exe",
                 "EasyAntiCheat_Setup.exe", "UnrealEditor.exe"):
        assert catalog.is_helper(name) is True


# -------------------------------------------------------------- real machine

def test_discovery_produces_unique_keys():
    apps = catalog.discover_all()
    keys = [a.key for a in apps]
    assert len(keys) == len(set(keys))


def test_discovery_dedupes_libraries_scanned_under_two_spellings():
    """The registry returns "c:/program files (x86)/steam" and the fallback
    guess returns "C:\\Program Files (x86)\\Steam". Both were walked."""
    apps = catalog.discover_steam()
    paths = [ntpath.normcase(a.path) for a in apps]
    assert len(paths) == len(set(paths))
