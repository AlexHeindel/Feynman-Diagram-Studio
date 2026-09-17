"""PyInstaller-friendly launcher for Feynman Diagram Studio."""

import sys

from feynman_studio.app import StudioApp, check_tk_version, main


if __name__ == "__main__":
    if sys.argv[1:] == ["--smoke-test"]:
        import tkinter as tk

        check_tk_version()
        root = tk.Tk()
        try:
            root.withdraw()
            StudioApp(root)
            root.update_idletasks()
        finally:
            root.destroy()
    else:
        main()
