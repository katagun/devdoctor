from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SVG = ROOT / "web" / "assets" / "devdoctor-icon.svg"
ICONSET_DIR = ROOT / ".build" / "devdoctor.iconset"
OUTPUT_ICNS = ROOT / "web" / "assets" / "devdoctor.icns"
ICON_SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
]


def main() -> None:
    rsvg = shutil.which("rsvg-convert")
    iconutil = shutil.which("iconutil")
    if not rsvg:
        raise SystemExit("Missing rsvg-convert. Install librsvg to regenerate the app icon.")
    if not iconutil:
        raise SystemExit("Missing iconutil. This script must run on macOS.")
    if not SOURCE_SVG.is_file():
        raise SystemExit(f"Missing icon source: {SOURCE_SVG}")

    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)

    for size, name in ICON_SIZES:
        subprocess.run(
            [
                rsvg,
                "--width",
                str(size),
                "--height",
                str(size),
                str(SOURCE_SVG),
                "--output",
                str(ICONSET_DIR / name),
            ],
            check=True,
        )

    subprocess.run(
        [iconutil, "--convert", "icns", "--output", str(OUTPUT_ICNS), str(ICONSET_DIR)],
        check=True,
    )
    print(OUTPUT_ICNS)


if __name__ == "__main__":
    main()
