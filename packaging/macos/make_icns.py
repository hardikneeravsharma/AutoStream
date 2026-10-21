"""Write the macOS app icon, AutoStream.icns, from the mark the UI draws.

    .venv/bin/python packaging/macos/make_icns.py [OUT]     (default build/macos/AutoStream.icns)

The Windows .ico comes from scripts/make_icon.py, which this imports rather
than copies: one drawing of the mark, two file formats. Written into build/,
not the tree -- it is a build product, regenerated every build, so it can never
drift from the .ico.

iconutil is Apple's own tool and the reliable way to an .icns that Finder,
the Dock and Launchpad all accept; Pillow's writer is the fallback when it is
missing (it is part of the Xcode command line tools).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from make_icon import render  # noqa: E402

DEFAULT_OUT = ROOT / "build" / "macos" / "AutoStream.icns"

# Apple's iconset: each size at 1x and 2x.
ICONSET = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
           (256, 1), (256, 2), (512, 1), (512, 2)]


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "AutoStream.iconset"
            iconset.mkdir()
            for size, scale in ICONSET:
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                render(size * scale).save(iconset / name)
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
                           check=True)
    else:
        render(1024).save(out, format="ICNS")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
