import sys
from pathlib import Path
import pytest
import tkinter as tk

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

@pytest.fixture(scope="session")
def tk_root():
    """Shared withdrawn Tk instance for tests requiring Tkinter widgets."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        try:
            root.destroy()
        except Exception:
            pass
    except Exception:
        # Headless environment fallback
        yield None
