"""Generates every app icon from one design (requires Pillow). Run after changing the icon or palette.

    assets/icon.ico              Windows exe / installer / shortcuts
    assets/icon.png              PC window + tray, Android in-app header
    assets/icon-512.png          Android launcher icon (older Android versions)
    assets/icon-fg.png, -bg.png  Android adaptive icon layers (Android 8+ launchers)
    assets/presplash.png         Android splash screen
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roliposter import palette  # noqa: E402

S = 1024
WHITE = (255, 255, 255, 255)


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def gradient(size: int) -> Image.Image:
    top, bottom = rgb(palette.ICON_GRADIENT_TOP), rgb(palette.ICON_GRADIENT_BOTTOM)
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        d.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return img


def arrows(size: int, scale: float = 1.0) -> Image.Image:
    """The two trade arrows on a transparent canvas; scale < 1 shrinks them toward the centre."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def arrow(y: int, rightward: bool, color) -> None:
        x0, x1, h, head = 250, 774, 70, 170
        if rightward:
            d.rectangle((x0, y - h // 2, x1 - head + 20, y + h // 2), fill=color)
            d.polygon([(x1 - head, y - 135), (x1, y), (x1 - head, y + 135)], fill=color)
        else:
            d.rectangle((x0 + head - 20, y - h // 2, x1, y + h // 2), fill=color)
            d.polygon([(x0 + head, y - 135), (x0, y), (x0 + head, y + 135)], fill=color)

    arrow(390, True, WHITE)
    arrow(634, False, (255, 255, 255, 230))
    if scale != 1.0:
        inner = img.resize((int(S * scale), int(S * scale)), Image.LANCZOS)
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        offset = (S - inner.width) // 2
        img.alpha_composite(inner, (offset, offset))
    return img.resize((size, size), Image.LANCZOS)


def tile() -> Image.Image:
    """Rounded blue tile with the arrows: the icon everywhere except Android's adaptive layers."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=255)
    img.paste(gradient(S), (0, 0), mask)
    marks = arrows(S)
    img.alpha_composite(marks)
    return img


def main() -> None:
    assets = ROOT / "assets"
    icon = tile()
    icon.save(assets / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.resize((256, 256), Image.LANCZOS).save(assets / "icon.png")
    icon.resize((512, 512), Image.LANCZOS).save(assets / "icon-512.png")
    # Adaptive icon: the launcher crops the layers to its own shape and keeps the middle 66% safe,
    # so the background is full-bleed and the arrows are shrunk into the safe zone.
    gradient(432).save(assets / "icon-bg.png")
    arrows(432, scale=0.85).save(assets / "icon-fg.png")  # 0.85 keeps every corner inside the safe circle
    splash = Image.new("RGBA", (S, S), rgb(palette.BG) + (255,))
    logo = icon.resize((320, 320), Image.LANCZOS)
    splash.paste(logo, (352, 352), logo)
    splash.save(assets / "presplash.png")
    print("wrote icons to", assets)


if __name__ == "__main__":
    main()
