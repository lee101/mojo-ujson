from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT, "python")
if PYTHON not in sys.path:
    sys.path.insert(0, PYTHON)
