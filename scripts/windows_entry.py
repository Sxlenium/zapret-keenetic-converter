"""Entry point for the standalone Windows GUI build."""

from __future__ import annotations

import sys

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        import tkinter  # noqa: F401

        from zapret_keenetic.gui import ConverterApp  # noqa: F401

        raise SystemExit(0)
    from zapret_keenetic.gui import main

    main()
