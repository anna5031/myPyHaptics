from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_tk_env() -> None:
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))

    # Allow importing bundled tkinter package copied as data files.
    if (base / "tkinter").is_dir() and str(base) not in sys.path:
        sys.path.insert(0, str(base))

    if "TCL_LIBRARY" not in os.environ:
        for dirname in ("tcl8.6", "tcl8"):
            candidate = base / dirname
            if candidate.is_dir():
                os.environ["TCL_LIBRARY"] = str(candidate)
                break

    if "TK_LIBRARY" not in os.environ:
        for dirname in ("tk8.6", "tk8"):
            candidate = base / dirname
            if candidate.is_dir():
                os.environ["TK_LIBRARY"] = str(candidate)
                break


_set_tk_env()
