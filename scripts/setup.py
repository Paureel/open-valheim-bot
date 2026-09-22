#!/usr/bin/env python3
"""Guided, resumable setup; never launches or controls Valheim."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.setup import main

if __name__ == "__main__":
    main()
