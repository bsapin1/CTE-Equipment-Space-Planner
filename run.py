#!/usr/bin/env python3
"""Launch the Streamlit app."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    app = Path(__file__).resolve().parent / "app.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app),
            "--server.port",
            "8502",
            "--server.address",
            "127.0.0.1",
            *sys.argv[1:],
        ],
        check=True,
    )
