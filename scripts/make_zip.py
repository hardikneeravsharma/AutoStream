r"""Zip a folder, surviving antivirus file locks, and verify the result.

WHY NOT Compress-Archive
    Two reasons, both learned the hard way on this project.

    It reports a per-file failure to PowerShell's error stream and then carries
    ON, so a run can look successful while the archive is missing files. The
    file it usually misses is _internal\base_library.zip, because Defender
    grabs a lock on it moments after PyInstaller writes it -- and that one file
    is the difference between an exe that starts and one that does not. A
    shipped zip that is quietly broken is the worst possible outcome here.

    And the lock is transient. Waiting a moment and trying again almost always
    works, which Compress-Archive will not do.

So: retry each file, then reopen the finished archive and check every single
source path made it in. Exits non-zero if anything is missing, and deletes the
archive rather than leaving a broken one lying around looking finished.

Run:  .venv\Scripts\python scripts\make_zip.py <source-dir> <out.zip>
"""
from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

# Defender's lock on a freshly written file clears in well under a second in
# practice. Backing off to ~8s total is generous and still fails fast enough to
# be a build step.
ATTEMPTS = 6
BACKOFF = 0.4


def _read(path: Path) -> bytes:
    last: OSError | None = None
    for i in range(ATTEMPTS):
        try:
            return path.read_bytes()
        except (PermissionError, OSError) as e:
            last = e
            time.sleep(BACKOFF * (i + 1))
    raise RuntimeError(f"could not read {path} after {ATTEMPTS} tries: {last}")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    if not src.is_dir():
        print(f"  [!!] not a directory: {src}")
        return 1

    files = sorted(p for p in src.rglob("*") if p.is_file())
    if not files:
        print(f"  [!!] nothing to archive in {src}")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)

    retried = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            rel = p.relative_to(src).as_posix()
            try:
                data = p.read_bytes()
            except (PermissionError, OSError):
                retried += 1
                print(f"  [--] locked, retrying: {rel}")
                data = _read(p)
            z.writestr(rel, data)

    # Reopen and compare against the source listing. Trusting the writer is
    # exactly the mistake Compress-Archive makes.
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        entries = set(z.namelist())
    expected = {p.relative_to(src).as_posix() for p in files}
    missing = sorted(expected - entries)

    if bad:
        print(f"  [!!] corrupt entry in the archive: {bad}")
        out.unlink(missing_ok=True)
        return 1
    if missing:
        print(f"  [!!] {len(missing)} file(s) missing from the archive:")
        for m in missing[:10]:
            print(f"       {m}")
        out.unlink(missing_ok=True)
        return 1

    mb = out.stat().st_size / 1024 / 1024
    note = f", {retried} retried past a lock" if retried else ""
    print(f"  [ok] archive verified - {len(entries)} entries{note}")
    print(f"       {out}  ({mb:,.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
