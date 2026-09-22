#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.config import Config
from valheim_codex.install import register_mcp
from valheim_codex.memory import Memory

parser = argparse.ArgumentParser(description="Prepare local app support and register this project's MCP server")
parser.add_argument("--home")
parser.add_argument("--no-mcp", action="store_true")
args = parser.parse_args()
config = Config(args.home).initialize()
Memory(config.home / "memory.sqlite3", config.settings["world_id"]).close()
if not args.no_mcp:
    if args.home:
        parser.error("Use default app support path for MCP registration; custom homes are for isolated tests")
    print(register_mcp(config))
print("Prepared " + str(config.home))
