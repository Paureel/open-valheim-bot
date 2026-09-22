#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.config import Config, ROOT
from valheim_codex.install import install_files

parser = argparse.ArgumentParser(description="Install only after normal manual play has been verified; never launches a game")
parser.add_argument("kind", choices=["bepinex", "bridge"])
parser.add_argument("--game-dir", required=True)
parser.add_argument("--normal-play-verified", action="store_true")
parser.add_argument("--bepinex-dir")
args = parser.parse_args()
running = subprocess.run(["/usr/bin/pgrep", "-x", "[Vv]alheim"], capture_output=True)
if running.returncode == 0:
    parser.error("Quit Valheim before installing game files. Nothing was installed.")
if running.returncode != 1:
    parser.error("Could not check whether Valheim is running; no files were installed")
if not args.normal_play_verified:
    parser.error("First verify unmodified game launch and manual server join, then pass --normal-play-verified")
game = Path(args.game_dir).expanduser().resolve()
if not list(game.rglob("assembly_valheim.dll")) and not list(game.rglob("Assembly-CSharp.dll")):
    parser.error("No managed game assemblies found at this Valheim path")
config = Config().initialize()
if args.kind == "bepinex":
    apps = list(game.glob("*.app"))
    if not apps:
        parser.error("This installer targets the native macOS Valheim Steam build")
    import plistlib
    with open(apps[0] / "Contents/Info.plist", "rb") as f:
        executable = plistlib.load(f)["CFBundleExecutable"]
    binary = apps[0] / "Contents/MacOS" / executable
    arch = subprocess.run(["file", str(binary)], capture_output=True, text=True, check=True).stdout
    if "x86_64" not in arch:
        parser.error("Current staged Doorstop is x86_64; installed game has no matching executable slice")
    source = ROOT / ".tools/bepinex-staged/BepInExPack_Valheim"
    if not source.exists():
        parser.error("Stage the inspected BepInEx pack first; see docs/INSTALL.md")
    manifest = install_files(source, game, config.home / "backups", "bepinex")
    (game / "start_game_bepinex.sh").chmod(0o755)
    print("Installed BepInEx files; restart/verify mod loading manually. Backup: " + str(manifest))
else:
    bep = Path(args.bepinex_dir).expanduser().resolve() if args.bepinex_dir else game / "BepInEx"
    log = bep / "LogOutput.log"
    if not log.exists() or "Chainloader startup complete" not in log.read_text(errors="replace"):
        parser.error("BepInEx successful startup log required before installing bridge")
    build = ROOT / "build"
    if not (build / "ValheimCodexBridge.dll").exists():
        parser.error("Run scripts/build.sh --plugin against the installed assemblies first")
    managed = list(game.glob("*.app/Contents/Resources/Data/Managed"))
    if len(managed) != 1:
        parser.error("One native macOS Valheim Managed directory is required")
    subprocess.run([sys.executable, str(ROOT / "scripts/verify-bindings.py"), str(managed[0])], check=True)
    # Only the two bridge assemblies belong to this installation.
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as directory:
        for name in ["ValheimCodexBridge.dll", "ValheimCodexBridge.Core.dll"]:
            shutil.copy2(build / name, Path(directory) / name)
        manifest = install_files(directory, bep / "plugins/ValheimCodexBridge", config.home / "backups", "bridge")
    print("Installed bridge; controls start paused. Complete acceptance stages A-J. Backup: " + str(manifest))
