#!/usr/bin/env python3
"""Start the read-only Web UI on 127.0.0.1:5001."""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.web.app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)