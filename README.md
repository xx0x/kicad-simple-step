# KiCad Simple STEP

Export KiCad board as a STEP optimized to be loadable by CAD software like Fusion (simplified STEP + PNGs).

A regular STEP export models every pad, track, silkscreen stroke and soldermask opening as real geometry. On a dense board that can be tens of megabytes of tiny faces that make CAD software crawl, even though an enclosure only needs the board's shape, its holes and the parts on it. This plugin exports just that, and puts the artwork back as pictures you can lay on the model.

## What it does

The plugin adds a button to the PCB editor's toolbar. Clicking it saves the board and writes three files next to the `.kicad_pcb`. They're named after the board, and each run overwrites them:

| File                        | Contents                                                                                                                                  |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `<board>-simple.step`       | The board body and component 3D models, without copper, silkscreen or soldermask geometry. Its origin is the centre of the board outline. |
| `<board>-simple-top.png`    | The top side, as seen from above.                                                                                                         |
| `<board>-simple-bottom.png` | The bottom side, as seen from below, so it's mirrored compared to KiCad's view.                                                           |

The pictures show copper, soldermask, pad finish and silkscreen in the colours set in the board's stackup, at 40 px/mm (about 1000 dpi). Each one covers exactly the board outline's bounding box. The area outside the outline, cutouts and pad holes are transparent.

To use them, put each picture on its face of the board, centred on the STEP's origin and scaled to the board's width and height. When the export finishes, the plugin shows the board's size.

## Requirements

- KiCad 10.0 or newer.
- The KiCad API turned on: **Preferences → Preferences → Plugins → Enable KiCad API**.

The first time you click the button, KiCad creates a Python environment for the plugin and installs its dependencies: [kicad-python](https://pypi.org/project/kicad-python/), [Pillow](https://pypi.org/project/pillow/) and [pypdfium2](https://pypi.org/project/pypdfium2/). This needs an internet connection and can take a minute.

## Installation

### From the repository (recommended)

The plugin isn't in KiCad's official repository, so add this one to the Plugin and Content Manager:

1. In the KiCad project window, open **Plugin and Content Manager**.
2. Click **Manage…** next to the repository list at the top.
3. Click **+** and paste this URL:

   ```
   https://raw.githubusercontent.com/xx0x/kicad-simple-step/main/repository.json
   ```

4. Click **Save**, then select **Simple STEP repository** in the repository list.
5. On the **Plugins** tab, find **Simple STEP**, click **Install**, then **Apply Pending Changes**.

Updates then show up in the Plugin and Content Manager like any other package.

### From a file

Download the zip from [`dist/`](dist/), then use **Install from File…** in the Plugin and Content Manager.

### After installing

Make sure the KiCad API is turned on (see [Requirements](#requirements)), then reopen the PCB editor. The **Simple STEP export** button appears in the top toolbar.

## Usage

Open a board in the PCB editor and click **Simple STEP export**. A small window shows which step is running: an export takes a few seconds to half a minute, depending on how many 3D models the board has. When it's done, a message lists the files it wrote, or explains what went wrong.

The board is saved before exporting, because the export works from the file on disk. That way the files always match what's on screen.

## How it works

Everything is produced with `kicad-cli` from the saved board:

- **STEP:** `kicad-cli pcb export step`, without copper, silkscreen or soldermask, and with the origin moved to the centre of the board outline.
- **Board shape:** a board-only STL export, read for the exact outline, cutouts and pad holes, from the same body the STEP has.
- **Artwork:** a black-and-white PDF of each copper, soldermask and silkscreen layer. These are rasterised with pdfium, cropped to the outline, and coloured from the stackup.

## Development

```
plugins/            the plugin itself: what KiCad installs
  plugin.json       KiCad API plugin description: the toolbar action and its icons
  simple_step.py    the toolbar action: talks to KiCad and shows the result
  exporter.py       the export itself: needs only kicad-cli, Pillow and pypdfium2
  requirements.txt  installed by KiCad into the plugin's environment
metadata.json       Plugin and Content Manager package description
resources/icon.png  package icon
tools/              icon drawing and package building
dist/, packages.json, resources.zip, repository.json
                    the published package and repository, generated by tools/build_package.py
```

To try the export without KiCad running, with Pillow and pypdfium2 installed:

```
python plugins/exporter.py path/to/board.kicad_pcb [path/to/kicad-cli]
```

To install a working copy straight into KiCad, copy or symlink `plugins/` to `<KiCad documents>/10.0/plugins/kicad-simple-step`. KiCad documents are in `~/Documents/KiCad` on macOS, `Documents\KiCad` on Windows, and `~/.local/share/KiCad` on Linux.

To release a new version:

1. Add it at the top of `versions` in `metadata.json`.
2. Run `python3 tools/build_package.py`.
3. Commit everything, including `dist/`, `packages.json`, `resources.zip` and `repository.json`, and push.

The repository URL points at the `main` branch, so pushing publishes the release.

`python3 tools/make_icons.py` redraws the icons. It needs Pillow.

## License

[MIT](LICENSE) © Vaclav Mach
