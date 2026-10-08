"""Export a KiCad board as a light STEP plus a picture of each side.

A full STEP export from KiCad models every pad, track, silkscreen stroke and soldermask opening as
real geometry. On a dense board that is most of the file and tens of thousands of tiny faces, and
the CAD program crawls through all of them, while an enclosure only cares about the board's
outline, its holes and how tall the parts are. So this writes, next to the board:

- ``<board>-simple.step``: board body and component models only, centred on the board outline.
- ``<board>-simple-top.png`` / ``<board>-simple-bottom.png``: copper, soldermask, finish and
  silkscreen of each side in the board's stackup colours, covering exactly the outline's bounding
  box at 40 px/mm. Outside the outline, cutouts and pad holes are transparent. Each is drawn as
  seen from its own side, so the bottom one is mirrored left to right.

Everything comes from kicad-cli, so it works from the saved board file:

- a board-only STL gives the board's exact shape - outline, cutouts and pad holes - from the same
  body the STEP has, and its bounding box;
- a black-and-white PDF of each copper, mask and silkscreen layer, rasterised with pdfium and
  cropped to that box, gives how much of each pixel every layer covers;
- the colours come from the stackup in the .kicad_pcb file.

Run directly for testing, with Pillow and pypdfium2 installed::

    python exporter.py path/to/board.kicad_pcb [path/to/kicad-cli]
"""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import pypdfium2
from PIL import Image, ImageChops, ImageDraw

PX_PER_MM = 40.0
PT_PER_MM = 72 / 25.4

# Our own pictures are big on purpose; Pillow would otherwise refuse them as a decompression bomb.
Image.MAX_IMAGE_PIXELS = None

# KiCad's stackup colour names. Unknown names fall back to green, the same as KiCad's default.
MASK_COLOURS = {
    "green": (25, 95, 55), "light green": (60, 140, 80), "saturated green": (20, 120, 40),
    "red": (150, 25, 25), "light red": (190, 60, 60), "red/orange": (190, 70, 30),
    "blue": (20, 55, 135), "light blue": (60, 110, 180), "dark blue": (15, 30, 80),
    "black": (18, 18, 20), "white": (230, 230, 228), "yellow": (210, 180, 30),
    "purple": (85, 35, 115), "grey": (110, 110, 110), "dark grey": (60, 60, 60),
    "light grey": (170, 170, 170),
}
SILK_COLOURS = {"white": (238, 238, 235), "black": (20, 20, 20), "yellow": (230, 200, 40)}
FINISH_COLOURS = {"gold": (212, 168, 72), "silver": (196, 198, 200), "copper": (190, 120, 70)}
# Bare FR4, seen where the mask is open and there is no copper.
SUBSTRATE = (190, 175, 120)

LAYERS = ["F.Cu", "F.Mask", "F.SilkS", "B.Cu", "B.Mask", "B.SilkS"]


class ExportError(Exception):
    pass


def output_paths(board_path):
    stem = os.path.splitext(board_path)[0]
    return {
        "step": stem + "-simple.step",
        "top": stem + "-simple-top.png",
        "bottom": stem + "-simple-bottom.png",
    }


def export(board_path, kicad_cli, say=print, tick=lambda: None):
    """Write the STEP and both pictures next to ``board_path``.

    ``say`` gets a line of progress before each step; ``tick`` is called often while kicad-cli
    runs, so a caller with a window can keep it responsive. Returns the output paths and the
    board's size in millimetres.
    """
    outputs = output_paths(board_path)
    with open(board_path, encoding="utf-8") as f:
        board_text = f.read()

    with tempfile.TemporaryDirectory() as tmp:
        say("Reading the board outline...")
        stl = os.path.join(tmp, "board.stl")
        run([kicad_cli, "pcb", "export", "stl", "--board-only", "--force", "--output", stl,
             board_path], "board outline export", tick)
        shape = BoardShape(stl)
        x0, y0, x1, y1 = shape.bbox
        size = (round((x1 - x0) * PX_PER_MM), round((y1 - y0) * PX_PER_MM))

        say("Exporting the STEP (board and parts only)...")
        centre = "{:.4f}x{:.4f}mm".format((x0 + x1) / 2, (y0 + y1) / 2)
        run([kicad_cli, "pcb", "export", "step", "--force", "--user-origin", centre,
             "--output", outputs["step"], board_path], "STEP export", tick)

        say("Drawing both sides...")
        coverage = layer_coverage(kicad_cli, board_path, shape.bbox, size, tmp, tick)
        alpha = shape.mask(size)
        colours = stackup_colours(board_text)
        finish = finish_colour(colours["finish"])
        for side, p in (("top", "F"), ("bottom", "B")):
            image = paint_side(
                coverage[p + ".Cu"], coverage[p + ".Mask"], coverage[p + ".SilkS"], alpha,
                colour(colours[p + ".Mask"], MASK_COLOURS, "green"),
                colour(colours[p + ".SilkS"], SILK_COLOURS, "white"), finish)
            if side == "bottom":
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            dpi = PX_PER_MM * 25.4
            image.save(outputs[side], optimize=True, dpi=(dpi, dpi))
            tick()

    return outputs, (x1 - x0, y1 - y0)


def run(command, what, tick):
    """Run kicad-cli quietly - it chatters about fonts and asserts - and only report what it said
    if it failed."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        while process.poll() is None:
            tick()
            time.sleep(0.05)
        if process.returncode != 0:
            log.seek(0)
            raise ExportError("{} failed:\n{}".format(
                what, log.read().decode("utf-8", "replace").strip()[-2000:]))


class BoardShape:
    """The board body from a board-only STL: its bounding box in KiCad's page coordinates (mm, Y
    down) and the triangles of its top face, which together cover exactly the board, minus
    cutouts and pad holes. Vias are not cut in that body, and do not need to be: the pictures show
    them as copper, not as holes."""

    def __init__(self, path):
        triangles = read_stl(path)
        if not triangles:
            raise ExportError("The board outline export came out empty - is Edge.Cuts closed?")
        xs = [v[0] for t in triangles for v in t[1:]]
        ys = [-v[1] for t in triangles for v in t[1:]]  # STL is Y up, KiCad Y down
        top = max(v[2] for t in triangles for v in t[1:])
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.top = [t[1:] for t in triangles
                    if t[0][2] > 0.99 and min(v[2] for v in t[1:]) > top - 1e-3]

    def mask(self, size):
        x0, y0, x1, y1 = self.bbox
        sx, sy = size[0] / (x1 - x0), size[1] / (y1 - y0)
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        for triangle in self.top:
            draw.polygon([((x - x0) * sx, (-y - y0) * sy) for x, y, _ in triangle], fill=255)
        return mask


def read_stl(path):
    """Triangles as (normal, a, b, c) tuples of (x, y, z), from an ASCII or binary STL."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:5] == b"solid" and b"facet" in data[:1000]:
        number = r"\s+([-+0-9.eE]+)"
        pattern = re.compile(("facet normal" + number * 3 + r"\s+outer loop"
                              + (r"\s+vertex" + number * 3) * 3).encode())
        triangles = []
        for match in pattern.finditer(data):
            values = [float(v) for v in match.groups()]
            triangles.append(tuple(tuple(values[i:i + 3]) for i in range(0, 12, 3)))
        return triangles
    count = struct.unpack_from("<I", data, 80)[0]
    return [tuple(tuple(struct.unpack_from("<3f", data, 84 + 50 * i + 12 * j)) for j in range(4))
            for i in range(count)]


def layer_coverage(kicad_cli, board_path, bbox, size, tmp, tick):
    """Plot each layer black-on-white to PDF and rasterise it cropped to ``bbox``, as how much of
    each pixel the layer covers (0-255).

    KiCad plots onto the drawing sheet in its own page coordinates, so cropping is a matter of
    cutting the page down to the board's bounding box.
    """
    pdf_dir = os.path.join(tmp, "pdf")
    run([kicad_cli, "pcb", "export", "pdf", "--mode-separate", "--black-and-white",
         "--drill-shape-opt", "2", "--layers", ",".join(LAYERS), "--output", pdf_dir,
         board_path], "layer plot", tick)
    x0, y0, x1, y1 = bbox
    coverage = {}
    for layer in LAYERS:
        # kicad-cli names the files after the layer's long name: F.SilkS becomes F_Silkscreen.
        suffix = "-" + layer.replace(".", "_").replace("SilkS", "Silkscreen") + ".pdf"
        name = next((n for n in os.listdir(pdf_dir) if n.endswith(suffix)), None)
        if name is None:
            raise ExportError("kicad-cli did not plot " + layer)
        page = pypdfium2.PdfDocument(os.path.join(pdf_dir, name))[0]
        width, height = page.get_size()
        crop = (x0 * PT_PER_MM, height - y1 * PT_PER_MM, width - x1 * PT_PER_MM, y0 * PT_PER_MM)
        if min(crop) < 0:
            raise ExportError("The board reaches outside its drawing sheet - move it onto the "
                              "sheet or pick a bigger one")
        grey = page.render(scale=PX_PER_MM / PT_PER_MM, crop=crop, grayscale=True).to_pil()
        grey = grey.convert("L")
        if grey.size != size:
            grey = grey.resize(size)
        coverage[layer] = ImageChops.invert(grey)
        tick()
    return coverage


def paint_side(copper, mask_open, silk, alpha, mask, silk_colour, finish):
    """Layer one face the way it is built: mask over bare board, a little lighter where copper
    runs under it, substrate or plated finish where the mask is open, then silkscreen on top -
    except on openings, where the fab clips it.

    The copper shows through as plain lightening rather than a copper tint: pours cover most of a
    board, and tinting them turns a black board brown."""
    mask_on_copper = tuple(round(c + (255 - c) * 0.08) for c in mask)
    covered = ImageChops.invert(mask_open)
    image = Image.new("RGB", alpha.size, mask)
    image.paste(mask_on_copper, mask=ImageChops.multiply(copper, covered))
    image.paste(SUBSTRATE, mask=ImageChops.multiply(mask_open, ImageChops.invert(copper)))
    image.paste(finish, mask=ImageChops.multiply(mask_open, copper))
    image.paste(silk_colour, mask=ImageChops.multiply(silk, covered))
    image.putalpha(alpha)
    return image


def stackup_colours(board_text):
    """Read the mask and silk colour of each side and the copper finish from the board's stackup."""
    stackup = board_text[board_text.find("(stackup"):] if "(stackup" in board_text else ""
    colours = {}
    for layer in ("F.SilkS", "F.Mask", "B.Mask", "B.SilkS"):
        match = re.search(r'\(layer "%s"(.*?)(?=\(layer "|\(copper_finish|$)' % re.escape(layer),
                          stackup, re.S)
        found = match and re.search(r'\(color "([^"]+)"\)', match.group(1))
        colours[layer] = found.group(1) if found else None
    finish = re.search(r'\(copper_finish "([^"]+)"\)', stackup)
    colours["finish"] = finish.group(1) if finish else None
    return colours


def colour(value, table, fallback):
    if value and value.startswith("#") and len(value) >= 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    return table.get((value or "").lower(), table[fallback])


def finish_colour(value):
    name = (value or "").lower()
    if any(word in name for word in ("gold", "enig", "enepig")):
        return FINISH_COLOURS["gold"]
    if "osp" in name or "copper" in name:
        return FINISH_COLOURS["copper"]
    return FINISH_COLOURS["silver"]


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: exporter.py BOARD.kicad_pcb [KICAD_CLI]")
    kicad_cli = sys.argv[2] if len(sys.argv) == 3 else shutil.which("kicad-cli")
    if not kicad_cli:
        sys.exit("kicad-cli not found - pass its path as the second argument")
    try:
        outputs, size = export(os.path.abspath(sys.argv[1]), kicad_cli)
    except ExportError as error:
        sys.exit(str(error))
    for path in outputs.values():
        print("  " + path)
    print("Board is {:g} x {:g} mm.".format(*size))


if __name__ == "__main__":
    main()
