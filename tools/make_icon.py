"""Generates assets/icon.ico (run once; requires Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024


def arrow(d: ImageDraw.ImageDraw, y: int, rightward: bool, color) -> None:
    x0, x1, h, head = 250, 774, 70, 170
    if rightward:
        d.rectangle((x0, y - h // 2, x1 - head + 20, y + h // 2), fill=color)
        d.polygon([(x1 - head, y - 135), (x1, y), (x1 - head, y + 135)], fill=color)
    else:
        d.rectangle((x0 + head - 20, y - h // 2, x1, y + h // 2), fill=color)
        d.polygon([(x0 + head, y - 135), (x0, y), (x0 + head, y + 135)], fill=color)


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bottom = (56, 189, 248), (37, 99, 235)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    arrow(d, 390, True, (255, 255, 255, 255))
    arrow(d, 634, False, (255, 255, 255, 230))
    out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.resize((256, 256), Image.LANCZOS).save(out.with_name("icon.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
