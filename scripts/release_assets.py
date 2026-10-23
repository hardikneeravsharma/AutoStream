"""Name a release's files, and checksum them, just before they are published.

    python scripts/release_assets.py VERSION DIR

The builds name their output the way they always have (build.ps1:
AutoStream-share.zip and AutoStream-<v>-setup.exe; build.sh:
AutoStream-macos-<arch>.dmg). What a release PUBLISHES is decided here, once,
for every platform (issue #206):

    AutoStream-<v>-windows-x64-setup.exe
    AutoStream-<v>-windows-x64.zip
    AutoStream-<v>-macos-arm64.dmg
    AutoStream-<v>-macos-x86_64.dmg

each with a .sha256 in the format `sha256sum -c` reads.

THE COMPATIBILITY COPY. Every Windows install up to v1.78.1 finds its update by
the name AutoStream-<v>-setup.exe and nothing else. So the installer is ALSO
published under that name, on every release: an old install updates through it
to a version whose updater knows the new names (updates.SETUP), and from then
on needs it no more.

It used to stop at v1.80.0, "two releases of runway" -- but releases came
several a day, so the runway was about a day long, and nobody updates on a
schedule. An install of v1.77.0 was then told v1.82.0 had "no package attached
to it - no installer and no zip", with eight files sitting on the page. There
is no version at which every old install is known to be gone, so there is no
version at which the copy can stop.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

def renames(version: str) -> dict[str, str]:
    """Build output name -> published name."""
    v = version.lstrip("vV")
    return {
        f"AutoStream-{v}-setup.exe": f"AutoStream-{v}-windows-x64-setup.exe",
        "AutoStream-share.zip": f"AutoStream-{v}-windows-x64.zip",
        "AutoStream-macos-arm64.dmg": f"AutoStream-{v}-macos-arm64.dmg",
        "AutoStream-macos-x86_64.dmg": f"AutoStream-{v}-macos-x86_64.dmg",
    }


def legacy(version: str) -> str:
    """The old-name installer every release carries -- see the docstring."""
    return f"AutoStream-{version.lstrip('vV')}-setup.exe"


def prepare(version: str, folder: Path) -> list[Path]:
    """Rename `folder`'s builds, add the compatibility copy, write every
    .sha256 afresh. -> the files to publish. Raises if a build is missing."""
    for old in folder.glob("*.sha256"):
        old.unlink()                      # the builds' own; rewritten below
    out = []
    for src, dst in renames(version).items():
        if not (folder / src).is_file():
            raise FileNotFoundError(f"the build did not produce {src}")
        (folder / src).rename(folder / dst)
        out.append(folder / dst)
    copy = legacy(version)
    shutil.copyfile(folder / renames(version)[copy], folder / copy)
    out.append(folder / copy)
    for f in list(out):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        side = f.with_name(f.name + ".sha256")
        side.write_text(f"{digest}  {f.name}\n", encoding="ascii", newline="\n")
        out.append(side)
    return out


if __name__ == "__main__":
    for p in prepare(sys.argv[1], Path(sys.argv[2])):
        print(p.name)
