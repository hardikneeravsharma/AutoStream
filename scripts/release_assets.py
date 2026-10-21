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
the name AutoStream-<v>-setup.exe and nothing else. So until LEGACY_UNTIL the
installer is ALSO published under that name: an old install updates through it
to a version whose updater knows the new names (updates.SETUP), and from then
on needs it no more. From LEGACY_UNTIL on the copy stops, by itself.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

# The first version published WITHOUT the old-name installer. Two releases of
# runway past the one that taught the updater the new names (v1.78.2).
LEGACY_UNTIL = (1, 80, 0)


def _v(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.lstrip("vV").split(".")[:3])


def renames(version: str) -> dict[str, str]:
    """Build output name -> published name."""
    v = version.lstrip("vV")
    return {
        f"AutoStream-{v}-setup.exe": f"AutoStream-{v}-windows-x64-setup.exe",
        "AutoStream-share.zip": f"AutoStream-{v}-windows-x64.zip",
        "AutoStream-macos-arm64.dmg": f"AutoStream-{v}-macos-arm64.dmg",
        "AutoStream-macos-x86_64.dmg": f"AutoStream-{v}-macos-x86_64.dmg",
    }


def legacy(version: str) -> str | None:
    """The old-name installer this release still carries, or None."""
    v = version.lstrip("vV")
    return f"AutoStream-{v}-setup.exe" if _v(v) < LEGACY_UNTIL else None


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
    if copy:
        shutil.copyfile(folder / renames(version)[f"AutoStream-{version.lstrip('vV')}-setup.exe"],
                        folder / copy)
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
