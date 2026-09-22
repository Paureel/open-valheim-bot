import hashlib
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path


def inspect_machine(game_dir=None):
    home = Path.home()
    steam = [p for p in (Path("/Applications/Steam.app"), home / "Applications/Steam.app") if p.exists()]
    libraries = []
    standard = home / "Library/Application Support/Steam/steamapps"
    if standard.exists():
        libraries.append(standard)
    # Known Whisky roots are checked explicitly; no unbounded home-directory scan.
    for root in [home / "Library/Containers/com.franke.Whisky/Bottles", home / "Library/Containers/com.isaacmarovitz.Whisky/Bottles"]:
        if root.exists():
            for bottle in root.iterdir():
                candidate = bottle / "drive_c/Program Files (x86)/Steam"
                if candidate.exists():
                    steam.append(candidate / "steam.exe")
                    libraries.append(candidate / "steamapps")
    for library in list(libraries):
        folders = library / "libraryfolders.vdf"
        if folders.exists():
            for match in re.findall(r'"path"\s+"([^"]+)"', folders.read_text(errors="replace")):
                extra = Path(match.replace("\\\\", "\\")) / "steamapps"
                if extra.exists() and extra not in libraries:
                    libraries.append(extra)
    games = [Path(game_dir).expanduser().resolve()] if game_dir else []
    for lib in libraries:
        manifest = lib / "appmanifest_892970.acf"
        if manifest.exists():
            match = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(errors="replace"))
            if match:
                games.append(lib / "common" / match[1])
        for name in ("Valheim", "valheim"):
            candidate = lib / "common" / name
            if candidate.exists() and candidate not in games:
                games.append(candidate)
    installs = []
    seen = set()
    for game in games:
        if not game.exists():
            continue
        identity = (game.stat().st_dev, game.stat().st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        assemblies = list(game.rglob("Assembly-CSharp.dll")) + list(game.rglob("assembly_valheim.dll")) if game.exists() else []
        managed = sorted(set(str(p.parent) for p in assemblies))
        dlls = [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in assemblies]
        bep = list(game.rglob("BepInEx.dll")) if game.exists() else []
        installs.append({"path": str(game), "native_macos": bool(list(game.glob("*.app"))),
            "managed_dirs": managed, "game_assemblies": dlls, "bepinex": [str(p) for p in bep]})
    codex = shutil.which("codex")
    version = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=10).stdout.strip() if codex else None
    return {"architecture": platform.machine(), "macos": platform.mac_ver()[0], "python": platform.python_version(),
        "codex": {"path": codex, "version": version}, "steam": [str(p) for p in steam if p.exists()],
        "steam_libraries": [str(p) for p in libraries], "valheim": installs,
        "game_launched": False, "server_join_tested": False, "mod_loading_verified": False,
        "next_gate": "Install native Steam and Valheim, then inspect current managed assemblies" if not installs else "Verify normal launch and joining before installing mods"}
