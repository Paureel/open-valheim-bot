#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.install import restore
parser = argparse.ArgumentParser(description="Restore backed-up installation files; preserve files changed since installation")
parser.add_argument("manifest")
args = parser.parse_args()
preserved = restore(args.manifest)
print("Restoration complete" if not preserved else "Preserved subsequently modified files:\n" + "\n".join(preserved))
