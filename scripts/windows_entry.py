"""Entry point for the standalone Windows GUI build."""

from __future__ import annotations

import sys

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        from tkinter import Tk

        from zapret_keenetic.gui import ConverterApp

        root = Tk()
        root.withdraw()
        try:
            ConverterApp(root)
            root.update_idletasks()
        finally:
            root.destroy()

        raise SystemExit(0)
    from zapret_keenetic.gui import main

    main()
