"""Bundles the RoValra browser extension (https://github.com/NotValra/RoValra) for the Received trades tab.

RoValra is free software by Valra under the GNU GPL v3.0. This script:
  1. downloads one pinned release and checks its SHA-256 (any other file is rejected),
  2. replaces the branding images that RoValra's license excludes from redistribution,
  3. adds tools/view_only_shim.js to the top of its background and content scripts, so it can't
     accept, decline, counter or send trades (the tab must stay view-only),
  4. writes NOTICE.txt and the GPL license next to it.
Output: vendor/rovalra/ (bundled into the app by build_exe.bat). Run: python tools/fetch_rovalra.py
"""
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

VERSION = "v2.6.16"
ZIP_URL = f"https://github.com/NotValra/RoValra/releases/download/{VERSION}/rovalra-{VERSION}.zip"
ZIP_SHA256 = "1c0760a0d597738ebe81308885d6fda28734b195d971c4a3b36c293719c405d9"
LICENSE_URL = f"https://raw.githubusercontent.com/NotValra/RoValra/{VERSION}/LICENSE"
SOURCE_URL = f"https://github.com/NotValra/RoValra/tree/{VERSION}"
PATCH_REVISION = "1"  # bump when the patches below change

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "vendor" / "rovalra"
SHIM = ROOT / "tools" / "view_only_shim.js"
PATCHED_SCRIPTS = ("background.js", "content.js")
# Assets the RoValra license excludes from the GPL (plus other logo art), replaced with neutral images.
BRANDING = ("public/Assets/icon-16.png", "public/Assets/icon-48.png", "public/Assets/icon-128.png",
            "public/Assets/RoValraLogo.png", "public/Assets/Contributor.png", "public/Assets/OldLogo/OldLogo.png",
            "public/Assets/DonatorTiers/Bronze.png", "public/Assets/DonatorTiers/Silver.png",
            "public/Assets/DonatorTiers/Gold.png", "public/Assets/DonatorTiers/Diamond.png")
BRANDING_SVG = ("public/Assets/logo.svg",)
NEUTRAL_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
               '<rect x="4" y="4" width="56" height="56" rx="14" fill="#3b4250"/></svg>\n')

NOTICE = f"""RoValra {VERSION} - bundled with Rolimons Ad Poster
=====================================================

RoValra is a free browser extension by Valra, licensed under the GNU General Public License v3.0
(see LICENSE in this folder). It is not made by, affiliated with, or endorsed by Valra or this app's authors.

Corresponding source: {SOURCE_URL}
Release file: {ZIP_URL}  (SHA-256 {ZIP_SHA256})

Changes made to RoValra for this app (by tools/fetch_rovalra.py in the Rolimons Ad Poster repository):
  1. The branding images excluded from RoValra's license (its logo, icons, contributor and donator art)
     were replaced with plain placeholder images.
  2. tools/view_only_shim.js was added to the top of background.js and content.js. It refuses requests
     that would change a Roblox trade (accept, decline, counter, send, cancel), because the app's
     Received trades tab is view-only. Everything else is unchanged.
"""


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def neutral_png(path: Path) -> None:
    size = Image.open(path).size if path.exists() else (128, 128)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    r = max(2, min(size) // 5)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=r, fill=(59, 66, 80, 255))
    img.save(path)


def build() -> Path:
    marker = OUT / "BUNDLE_VERSION"
    wanted = f"{VERSION} {ZIP_SHA256} patch {PATCH_REVISION} shim {hashlib.sha256(SHIM.read_bytes()).hexdigest()}"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == wanted:
        print(f"RoValra {VERSION} already prepared in {OUT}")
        return OUT

    data = download(ZIP_URL)
    digest = hashlib.sha256(data).hexdigest()
    if digest != ZIP_SHA256:
        sys.exit(f"RoValra download checksum mismatch: got {digest}, expected {ZIP_SHA256}. Refusing to bundle it.")

    staging = OUT.with_name("rovalra.tmp")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(staging)
    if not (staging / "manifest.json").exists():
        sys.exit("Unexpected RoValra release layout (no manifest.json at the top).")

    for rel in BRANDING:
        neutral_png(staging / rel)
    for rel in BRANDING_SVG:
        if (staging / rel).exists():
            (staging / rel).write_text(NEUTRAL_SVG, encoding="utf-8")

    shim = SHIM.read_text(encoding="utf-8")
    for name in PATCHED_SCRIPTS:
        script = staging / name
        if not script.exists():
            sys.exit(f"Unexpected RoValra release layout ({name} missing); the view-only patch can't be applied.")
        script.write_text(shim + "\n" + script.read_text(encoding="utf-8"), encoding="utf-8")

    (staging / "LICENSE").write_bytes(download(LICENSE_URL))
    (staging / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    (staging / "BUNDLE_VERSION").write_text(wanted + "\n", encoding="utf-8")

    shutil.rmtree(OUT, ignore_errors=True)
    staging.rename(OUT)
    print(f"Prepared RoValra {VERSION} in {OUT}")
    return OUT


if __name__ == "__main__":
    build()
