"""Draw the plugin's icons: the toolbar button at 24 and 48 px for light and dark themes, and the
64 px package icon the Plugin and Content Manager shows.

An isometric board with one part on it - the STEP this plugin exports. Drawn 8x larger and scaled
down, so the small sizes stay smooth. Needs Pillow; run from anywhere.
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPERSAMPLE = 8

BOARD_TOP = (58, 138, 74)
BOARD_SIDE = (36, 96, 58)
PART_TOP = (226, 226, 226)
PART_LEFT = (160, 160, 160)
PART_RIGHT = (190, 190, 190)


def iso(cx, cy, w, h, lift):
    """An isometric box's top face and two visible sides, centred at (cx, cy), in unit space."""
    top = [(cx - w, cy), (cx, cy - h), (cx + w, cy), (cx, cy + h)]
    left = [(cx - w, cy), (cx, cy + h), (cx, cy + h + lift), (cx - w, cy + lift)]
    right = [(cx, cy + h), (cx + w, cy), (cx + w, cy + lift), (cx, cy + h + lift)]
    return top, left, right


def draw(size, outline):
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    # A thinner outline at toolbar size, where the thick one swallows the part.
    width = max(1, round(big / (32 if size <= 24 else 22)))

    def shape(points, fill):
        points = [(x * big, y * big) for x, y in points]
        pen.polygon(points, fill=fill)
        pen.line(points + points[:1], fill=outline, width=width, joint="curve")

    top, left, right = iso(0.5, 0.58, 0.44, 0.24, 0.12)
    shape(left, BOARD_SIDE)
    shape(right, BOARD_SIDE)
    shape(top, BOARD_TOP)
    top, left, right = iso(0.5, 0.40, 0.2, 0.11, 0.16)
    shape(left, PART_LEFT)
    shape(right, PART_RIGHT)
    shape(top, PART_TOP)
    return image.resize((size, size), Image.LANCZOS)


def main():
    icons = os.path.join(ROOT, "plugins", "icons")
    os.makedirs(icons, exist_ok=True)
    for theme, outline in (("light", (40, 40, 40)), ("dark", (225, 225, 225))):
        draw(24, outline).save(os.path.join(icons, "icon-{}.png".format(theme)))
        draw(48, outline).save(os.path.join(icons, "icon-{}@2x.png".format(theme)))
    os.makedirs(os.path.join(ROOT, "resources"), exist_ok=True)
    draw(64, (40, 40, 40)).save(os.path.join(ROOT, "resources", "icon.png"))


if __name__ == "__main__":
    main()
