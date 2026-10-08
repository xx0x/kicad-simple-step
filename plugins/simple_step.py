"""Toolbar action: save the open board, export it with exporter.py next to the board file, and say
how it went.

KiCad runs this in the plugin's own virtual environment and tells it where to reach the running
editor through KICAD_API_SOCKET and KICAD_API_TOKEN, which kicad-python picks up by itself.

The board is saved first because the export works from the file on disk, through kicad-cli, and
should match what is on screen.

A small window shows which step is running - the export takes a while, and a button that seems
to do nothing gets clicked again - and is replaced by the result at the end. Both use wxPython,
which KiCad ships with its own Python and makes visible to the plugin's environment. The plugin is
a process of its own, though, not part of KiCad, and on macOS a process like that starts in the
background: its windows open behind the editor, where nobody sees them. So before showing
anything it turns itself into an accessory app (no Dock icon) and brings itself to the front, and
its windows stay on top. Without wx, progress and result only go to the console.
"""

import os
import sys
import traceback

from kipy import KiCad

import exporter

TITLE = "Simple STEP export"


def board_path(board):
    name = board.name
    if os.path.isabs(name):
        return name
    return os.path.join(board.get_project().path, name)


def run_export(ui):
    """Save and export the open board. Returns (message, is_error)."""
    try:
        kicad = KiCad()
        board = kicad.get_board()
        path = board_path(board)
        ui.say("Saving " + os.path.basename(path) + "...")
        board.save()
        outputs, size = exporter.export(path, kicad.get_kicad_binary_path("kicad-cli"),
                                        say=ui.say, tick=ui.tick)
    except exporter.ExportError as error:
        return "Export failed:\n\n" + str(error), True
    except Exception:
        return "Export failed:\n\n" + traceback.format_exc(), True
    return ("Export OK, these files were created in\n{}:\n\n{}\n\n"
            "The pictures cover the board outline exactly: {:g} x {:g} mm.".format(
                os.path.dirname(path),
                "\n".join(os.path.basename(p) for p in outputs.values()), *size)), False


def bring_to_front():
    """On macOS, make this process an accessory app and activate it, so its windows show above the
    PCB editor. Purely cosmetic - any failure just leaves the window where macOS puts it."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend

        send.restype = ctypes.c_void_p
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        app = send(objc.objc_getClass(b"NSApplication"),
                   objc.sel_registerName(b"sharedApplication"))
        send.restype = ctypes.c_bool
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        send(app, objc.sel_registerName(b"setActivationPolicy:"), 1)  # Accessory
        send.restype = None
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        send(app, objc.sel_registerName(b"activateIgnoringOtherApps:"), True)
    except Exception:
        pass


class Ui:
    """The progress window while exporting, then the result. Falls back to the console without wx."""

    # Saving, then the three steps exporter.export() announces.
    STEPS = 4

    def __init__(self):
        self.step = 0
        try:
            import wx
        except ImportError:
            self.wx = None
            return
        self.wx = wx
        self.app = wx.App()
        bring_to_front()
        self.window = wx.Dialog(None, title=TITLE, style=wx.CAPTION | wx.STAY_ON_TOP)
        self.label = wx.StaticText(self.window, label="Starting...")
        self.gauge = wx.Gauge(self.window, range=self.STEPS, size=(420, -1))
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(self.label, 0, wx.EXPAND | wx.ALL, 12)
        column.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.window.SetSizerAndFit(column)
        self.window.CentreOnScreen()
        self.window.Show()
        self.window.Raise()
        self.tick()

    def say(self, text):
        self.step += 1
        text = "Step {} of {}: {}".format(self.step, self.STEPS, text)
        print(text)
        if self.wx:
            self.label.SetLabel(text)
            self.gauge.SetValue(self.step - 1)
            self.tick()

    def tick(self):
        if self.wx:
            self.app.Yield(True)

    def finish(self, message, error):
        print(message, file=sys.stderr if error else sys.stdout)
        if not self.wx:
            return
        wx = self.wx
        self.window.Destroy()
        dialog = wx.Dialog(None, title=TITLE, style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        icon = wx.StaticBitmap(dialog, bitmap=wx.ArtProvider.GetBitmap(
            wx.ART_ERROR if error else wx.ART_INFORMATION, wx.ART_MESSAGE_BOX))
        text = wx.StaticText(dialog, label=message)
        text.Wrap(600)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(icon, 0, wx.ALL, 12)
        row.Add(text, 1, wx.TOP | wx.BOTTOM | wx.RIGHT, 12)
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(row, 1, wx.EXPAND)
        column.Add(dialog.CreateStdDialogButtonSizer(wx.OK), 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        dialog.SetSizerAndFit(column)
        dialog.CentreOnScreen()
        dialog.Raise()
        dialog.ShowModal()
        dialog.Destroy()


def main():
    ui = Ui()
    message, error = run_export(ui)
    ui.finish(message, error)
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
