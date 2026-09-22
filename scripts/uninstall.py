#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.config import Config
from valheim_codex.install import restore, unregister_mcp
from valheim_codex.protocol import LocalClient
parser = argparse.ArgumentParser(description="Unregister MCP, stop services, and restore bridge files. Memories are preserved.")
parser.add_argument("--include-bepinex", action="store_true", help="Also restore BepInEx files installed by this project; may affect other mods")
args = parser.parse_args()
config = Config()
if not config.home.exists():
    print("Nothing installed"); sys.exit(0)
try:
    LocalClient(config).request("/control/shutdown", {})
except Exception:
    try: LocalClient(config,"bridge").request("/control/stop",{},timeout=2)
    except Exception: pass
unregister_mcp(config)
backups = config.home / "backups"
patterns = ["bridge-*/manifest.json"] + (["bepinex-*/manifest.json"] if args.include_bepinex else [])
for pattern in patterns:
    for manifest in sorted(backups.glob(pattern), reverse=True):
        for file in restore(manifest):
            print("Preserved modified file: " + file)
print("Uninstalled bridge integration. Memory, profiles, logs, and backups preserved at " + str(config.home))
print("Remove that folder manually only if you also want to erase your character's memories.")
