"""
GBA Compilation Builder - desktop app entry point.

  python app.py                                   start the window
  GBABuilder.exe --selftest <fixtures> <result>   headless check used by the
                                                  automated Windows build
"""

import os
import sys
import traceback


def run_selftest(argv):
    fixtures, result_file = argv[2], argv[3]
    try:
        import engine
        ok, text = engine.selftest(fixtures)
    except Exception:
        ok, text = False, traceback.format_exc()
    with open(result_file, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest":
        sys.exit(run_selftest(sys.argv))

    try:                                   # crisp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        import gui
        gui.main()
    except Exception:
        # A windowed .exe has no console, so leave a note the user can send me.
        crash = os.path.join(os.path.expanduser("~"), "gba-builder-crash.txt")
        try:
            with open(crash, "w", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        except OSError:
            pass
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror(
                "GBA Compilation Builder",
                "The app hit an unexpected problem and had to close.\n\n"
                f"Details were saved to:\n{crash}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
