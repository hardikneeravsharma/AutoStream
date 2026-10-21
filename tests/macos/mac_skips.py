"""Tests the Mac does not run, and why: almost all pin WINDOWS behaviour.

The offline suite was written on Windows and some of it asserts how Windows
does a thing: winget installs, NVENC/AMF/Quick Sync probes, the WebView2
registry key, `cmd /c`, drive letters, the release updater. On a Mac those
paths are not taken -- the macOS build answers the same questions its own way
(issue #193), and tests/macos/ covers that answer.

So on a Mac, and ONLY on a Mac, tests/conftest.py skips what is listed here.
Every entry names its reason, because "not run" must never be mistakable for
"passing". Nothing here changes what runs on Windows.

An entry is a node id, or a test file to skip whole.
"""
from __future__ import annotations

_GPU = ("probes NVENC, AMF, Quick Sync, CUDA and D3D11VA, which a Mac ffmpeg "
        "does not have; tests/macos/test_macos_encode.py covers VideoToolbox")
_UPDATER = ("the Windows installer: chosen over the zip and launched silently. A "
            "Mac takes its .dmg and swaps the app itself "
            "(tests/macos/test_macos_updates.py)")
_CMD = "runs `cmd /c`, which only Windows has"

SKIP_ON_MAC: dict[str, str] = {
    "tests/test_gpu_probe.py": _GPU,
    "tests/test_update_install.py::test_a_zip_says_what_to_do_with_it_instead_of_running_it": _UPDATER,
    "tests/test_update_install.py::test_the_installer_is_started_silently_and_restarts_the_app": _UPDATER,
    "tests/test_update_install.py::test_the_app_leaves_after_replying_not_before": _UPDATER,
    "tests/test_update_install.py::test_a_failure_to_start_is_reported_not_raised": _UPDATER,
    "tests/test_updates.py::test_the_installer_is_chosen_over_the_zip": _UPDATER,
    "tests/test_updates.py::test_the_newest_installer_wins_if_a_release_carries_several": _UPDATER,
    "tests/test_webview2.py": "reads the Edge WebView2 key from the Windows registry",
    "tests/test_clip_diagnostics.py::test_tools_run_reports_to_whoever_is_recording": _CMD,
    "tests/test_clip_diagnostics.py::test_a_process_that_failed_is_recorded_before_the_error_is_raised": _CMD,
    "tests/test_clip_diagnostics.py::test_a_recorder_that_throws_cannot_break_a_clip_run": _CMD,
    "tests/test_clip_diagnostics.py::test_a_folder_that_cannot_be_written_gives_an_empty_path_not_a_crash":
        "Z:/ is a missing drive only on Windows; on a Mac it is a relative "
        "folder, which the test then creates inside the checkout",
    "tests/test_clips.py::test_history_never_raises_on_a_bad_path":
        "Z:/ is a missing drive only on Windows; on a Mac it is a relative "
        "folder that can be written",
    "tests/test_clip_review.py::test_a_path_is_compared_by_what_it_points_at":
        "expects Windows' case- and slash-folding of a C:\\ path",
    "tests/test_deps.py::test_an_install_refuses_rather_than_failing_when_winget_is_absent":
        "winget; a Mac installs with Homebrew (tests/macos/test_macos_deps.py)",
    "tests/test_deps.py::test_a_missing_tesseract_raises_something_that_says_what_to_do":
        "hides Tesseract from the Windows lookups only; tests/macos/test_macos_deps.py",
    "tests/test_no_dialogs_under_test.py::test_a_real_run_is_unaffected":
        "fakes the Tk picker, which a Mac never uses -- it would reach the "
        "real AppleScript picker and open it on the screen",
    "tests/test_share_codes.py::test_requesting_a_download_never_raises":
        "fakes os.startfile; a Mac refuses the game-fetch link outright "
        "(tests/macos/test_macos_features.py)",
    "tests/test_valorant_match.py::test_fetch_now_says_what_to_open_when_the_client_is_closed":
        "the Riot Client fetch; a Mac refuses it (tests/macos/test_macos_features.py)",
    "tests/test_valorant_match.py::test_fetch_now_answers_for_the_recording_on_the_page":
        "the Riot Client fetch; a Mac refuses it (tests/macos/test_macos_features.py)",
    # Not Windows behaviour, and not a Mac bug: a threshold the Mac's ffmpeg
    # lands just under. _frame_at BLENDS flow frames, so no frame repeats; frame
    # 55's neighbours differ by a mean 0.296 grey levels against a 0.3 cut-off
    # on Homebrew's ffmpeg 9.0.2. Fails the same on a clean main (#194).
    "tests/test_valorant.py::test_spans_read_in_parallel_come_back_in_time_order":
        "fakes valorant_feed._span, which a Mac replaces with the shared decode "
        "(macos/scan.py); tests/macos/test_macos_scan.py pins the same order",
    "tests/test_retime.py::test_a_rendered_retime_has_every_frame_and_slow_motion_is_not_repeats":
        "borderline: frame 55 differs by 0.296 against a 0.3 repeat cut-off under "
        "Homebrew's ffmpeg 9.0.2 -- blended, not repeated",
}


def reason_for(nodeid: str) -> str:
    """The reason `nodeid` is skipped on a Mac, or ""."""
    for key, why in SKIP_ON_MAC.items():
        if nodeid == key or nodeid.startswith((key + "::", key + "[")):
            return why
    return ""
