"""Generate the PWA icons from the locked cipher-grid mark.

One spec, one place. The mark is a 4x4 grid on a 64 unit box: cell 13, gap 3,
offset 1.5, corner radius 1.6, with four cells voided. Drawing it from those
numbers rather than tracing a PNG means the app icon and the in-app mark cannot
drift apart.

Maskable icons get an opaque ground and a smaller mark, because Android crops
them to whatever shape the launcher wants and anything in the outer 20% is at
risk of being cut off.

    python3 tools/gen_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src/static/icons"

BOX, CELL, GAP, OFFSET, RADIUS = 64, 13, 3, 1.5, 1.6
VOIDS = {(0, 0), (1, 2), (2, 1), (3, 3)}     # (row, col)

INK_DARK = (242, 242, 244, 255)              # --accent, dark mode
GROUND = (13, 13, 15, 255)                   # --bg, dark mode


def draw_mark(size: int, ink, ground=None, coverage: float = 1.0) -> Image.Image:
    """Render at 4x and downsample: the corner radii are small and alias badly."""
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale), ground or (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)

    unit = (size * scale * coverage) / BOX
    pad = (size * scale - BOX * unit) / 2

    for row in range(4):
        for col in range(4):
            if (row, col) in VOIDS:
                continue
            x = pad + (OFFSET + col * (CELL + GAP)) * unit
            y = pad + (OFFSET + row * (CELL + GAP)) * unit
            pen.rounded_rectangle(
                [x, y, x + CELL * unit, y + CELL * unit],
                radius=RADIUS * unit, fill=ink,
            )
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []

    for size in (192, 512):
        # "any" purpose: transparent, so it sits on whatever the surface is.
        draw_mark(size, INK_DARK).save(OUT / f"icon-{size}.png")
        written.append(f"icon-{size}.png")
        # "maskable": opaque, mark pulled in to survive the launcher's crop.
        draw_mark(size, INK_DARK, ground=GROUND, coverage=0.62).save(
            OUT / f"maskable-{size}.png")
        written.append(f"maskable-{size}.png")

    # iOS never applies a mask but does composite on white if there is no ground.
    draw_mark(180, INK_DARK, ground=GROUND, coverage=0.68).save(OUT / "apple-touch-icon.png")
    written.append("apple-touch-icon.png")

    for name in written:
        print(f"  {name:26} {(OUT / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
