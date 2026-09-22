"""Operator-only setup. Preparation never writes into the game installation."""
import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from .config import Config, ROOT

BEPINEX_VERSION = "5.4.2350"
BEPINEX_SHA256 = "37a91c000b4e88f2ed7a4bd7d812239852d2e36cbf0ff0a9f5faacfba46b105f"
BEPINEX_URL = "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2350/"


def game_path(explicit=None):
    saved = ROOT / ".tools/game-dir"
    chosen = explicit or os.environ.get("VALHEIM_GAME_DIR")
    if not chosen and saved.exists():
        chosen = saved.read_text().strip()
    if chosen:
        return Path(chosen).expanduser().resolve()
    steam = Path.home() / "Library/Application Support/Steam"
    libraries = [steam]
    vdf = steam / "steamapps/libraryfolders.vdf"
    if vdf.exists():
        libraries += [Path(p.replace("\\\\", "\\")) for p in
                      re.findall(r'"path"\s+"([^"]+)"', vdf.read_text())]
    games = list(dict.fromkeys((p / "steamapps/common/Valheim").resolve()
                 for p in libraries if (p / "steamapps/common/Valheim/valheim.app").is_dir()))
    if len(games) != 1:
        raise RuntimeError("Choose the official native installation with --game-dir '/path/to/Valheim'.")
    return games[0]


def validate_game(game):
    managed = game / "valheim.app/Contents/Resources/Data/Managed"
    reviewed = json.loads((ROOT / "bridge/Plugin/reviewed-assemblies.json").read_text())
    for name, expected in reviewed.items():
        path = managed / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Unsupported game files: " + name + ". This adapter requires the reviewed "
                               "Valheim 1.0.15 build 25390630. See docs/TROUBLESHOOTING.md.")
    return managed


def native_python(explicit=None):
    candidates = [explicit] if explicit else [sys.executable, shutil.which("python3.12"),
        "/opt/homebrew/bin/python3.12", "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        check = subprocess.run([str(candidate), "-c", "import platform,sys; "
            "sys.exit(not (sys.version_info[:2] == (3,12) and platform.machine() == 'arm64'))"],
            capture_output=True, timeout=10)
        if check.returncode == 0:
            return str(Path(candidate).absolute())
    raise RuntimeError("Native arm64 Python 3.12 is required. Install python@3.12 with Homebrew "
                       "or the Python.org macOS installer, then retry with --python /path/to/python3.12.")


def checked_archive(archive, expected):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError("BepInEx archive checksum mismatch; nothing extracted. Remove the cached ZIP and retry.")
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise RuntimeError("Unsafe path in BepInEx archive")


def stage_bepinex():
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    archive = tools / ("BepInExPack_Valheim-" + BEPINEX_VERSION + ".zip")
    if not archive.exists():
        print("Downloading pinned BepInEx " + BEPINEX_VERSION, flush=True)
        partial = archive.with_suffix(".partial")
        try:
            # The registry rejects urllib's default client on some networks.
            # Use macOS curl, then verify the pinned bytes before extraction.
            subprocess.run(["/usr/bin/curl", "--fail", "--location", "--retry", "2",
                "--connect-timeout", "20", "--max-time", "300", "--silent", "--show-error",
                BEPINEX_URL, "--output", str(partial)], check=True)
            checked_archive(partial, BEPINEX_SHA256)
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    checked_archive(archive, BEPINEX_SHA256)
    destination = tools / "bepinex-staged"
    with zipfile.ZipFile(archive) as package:
        if destination.exists():
            for entry in package.infolist():
                if entry.is_dir():
                    continue
                target = destination / entry.filename
                if not target.resolve().is_relative_to(destination.resolve()) or not target.is_file() or target.read_bytes() != package.read(entry):
                    raise RuntimeError("Staged BepInEx differs from the verified archive. Move .tools/bepinex-staged aside and retry.")
        else:
            with tempfile.TemporaryDirectory(dir=tools) as temporary:
                package.extractall(temporary)
                Path(temporary).rename(destination)
    print("BepInEx archive and staged files verified.", flush=True)


def require_game_closed():
    result = subprocess.run(["/usr/bin/pgrep", "-x", "[Vv]alheim"], capture_output=True)
    if result.returncode == 0:
        raise RuntimeError("Quit Valheim before installing game files. No files were installed.")
    if result.returncode != 1:
        raise RuntimeError("Could not check the game process; no files were installed.")


def run(command, dry_run=False, env=None):
    print("+ " + shlex.join([str(x) for x in command]), flush=True)
    if not dry_run:
        subprocess.run([str(x) for x in command], cwd=ROOT, env=env, check=True)


def prepare(args, game):
    managed = validate_game(game)
    python = native_python(args.python)
    if not shutil.which("codex"):
        raise RuntimeError("Codex executable not found. Install/sign in to Codex; see docs/TUTORIAL.md.")
    print("Preparing local files. The 1.7 GB model and its Python dependencies need several GB of disk space.")
    if args.dry_run:
        print("Would download/check and stage pinned BepInEx; preserve existing private settings.")
    else:
        stage_bepinex()
    sdk = ROOT / ".tools/dotnet/dotnet"
    reference = ROOT / ".tools/packages/netstandard.library.ref.2.1.0.nupkg"
    if not sdk.is_file() or not reference.is_file():
        run([ROOT / "scripts/bootstrap-toolchain.sh"], args.dry_run)
    env = dict(os.environ, VALHEIM_MANAGED_DIR=str(managed),
               VALHEIM_BEPINEX_DIR=str(ROOT / ".tools/bepinex-staged/BepInExPack_Valheim/BepInEx"))
    run([ROOT / "scripts/build.sh", "--plugin"], args.dry_run, env)
    run([python, ROOT / "scripts/setup-system-one.py"], args.dry_run)
    run([python, ROOT / "scripts/install-local.py", "--no-mcp"], args.dry_run)
    if not args.dry_run:
        if "\n" in str(game) or "\r" in str(game):
            raise RuntimeError("Game paths containing newlines are not supported")
        (ROOT / ".tools/game-dir").write_text(str(game) + "\n")
    print("Preparation plan complete." if args.dry_run else
          "Prepared. Next: verify normal Steam play, quit Valheim, then run ./setup.command loader.")


def install_stage(args, game):
    validate_game(game)
    if not args.dry_run:
        require_game_closed()
    if not args.normal_play_verified and not args.dry_run:
        if not sys.stdin.isatty() or input("Have you joined this world normally through Steam and then quit Valheim? [y/N] ").lower() not in ("y", "yes"):
            raise RuntimeError("Join normally and quit first; rerun with --normal-play-verified when complete.")
    kind = "bepinex" if args.step == "loader" else "bridge"
    if args.step == "loader" and not args.dry_run:
        if (game / "BepInEx/core/BepInEx.dll").exists():
            raise RuntimeError("BepInEx is already installed. Verify its version/log and use the bridge step; "
                               "this assistant will not overwrite another loader installation.")
        stage_bepinex()
    if args.step == "bridge":
        managed = game / "valheim.app/Contents/Resources/Data/Managed"
        env = dict(os.environ, VALHEIM_MANAGED_DIR=str(managed))
        run([ROOT / "scripts/build.sh", "--plugin"], args.dry_run, env)
    run([sys.executable, ROOT / "scripts/install-game-files.py", kind,
         "--game-dir", game, "--normal-play-verified"], args.dry_run)
    print("Next: launch with scripts/launch-game.command, verify BepInEx loads, then quit and run ./setup.command bridge."
          if args.step == "loader" else
          "Next: launch with scripts/launch-game.command, join with your character, then run ./setup.command player.")


def check(game, python=None):
    checks = []
    for label, operation in [("Reviewed game assemblies", lambda: validate_game(game)),
                             ("Native Python 3.12", lambda: native_python(python))]:
        try:
            operation(); checks.append((label, True))
        except (RuntimeError, OSError):
            checks.append((label, False))
    config = Config()
    checks.extend([
        ("Codex executable", bool(shutil.which("codex"))),
        ("OpenJev environment", (ROOT / ".tools/system-one/bin/python").is_file()),
        ("OpenJev weights downloaded", (ROOT / ".tools/models/openjev-0.8b/model.safetensors").is_file()),
        ("Bridge built", all((ROOT / "build" / name).is_file() for name in ["ValheimCodexBridge.dll", "ValheimCodexBridge.Core.dll"])),
        ("BepInEx installed", (game / "BepInEx/core/BepInEx.Preloader.dll").is_file()),
        ("Bridge installed", all((game / "BepInEx/plugins/ValheimCodexBridge" / name).is_file() for name in ["ValheimCodexBridge.dll", "ValheimCodexBridge.Core.dll"])),
        ("Player/world configured", config.settings["world_id"].startswith("world:") and bool(config.settings["character_name"])),
    ])
    for label, ok in checks:
        print(("OK       " if ok else "MISSING  ") + label)
    print("Game: " + str(game))
    print("This checks local files only. It does not verify login, model access, live bridge health, or gameplay reliability.")
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", nargs="?", choices=["prepare", "loader", "bridge", "player", "check"])
    parser.add_argument("--game-dir", help="Official Steam Valheim folder (saved by prepare)")
    parser.add_argument("--python", help="Native arm64 Python 3.12 executable")
    parser.add_argument("--normal-play-verified", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without downloads, writes, or game inputs")
    args = parser.parse_args(argv)
    try:
        if platform.system() != "Darwin":
            raise RuntimeError("This setup supports native Valheim on macOS Apple Silicon only.")
        if not args.step:
            if not sys.stdin.isatty():
                parser.error("Choose prepare, loader, bridge, player, or check (see docs/TUTORIAL.md).")
            print("Valheim AI setup\n1  Prepare dependencies and build\n2  Install BepInEx (game closed)\n"
                  "3  Install bridge (after first BepInEx launch)\n4  Bind player/world (in-game)\n5  Check installation\n")
            args.step = {"1":"prepare", "2":"loader", "3":"bridge", "4":"player", "5":"check"}.get(input("Choose a step [5]: ").strip() or "5")
            if not args.step:
                raise RuntimeError("Choose a step from 1 to 5.")
        if args.step == "player":
            run([sys.executable, ROOT / "scripts/configure-player.py"], args.dry_run)
            if args.dry_run:
                print("Would ask you to confirm the displayed identity before applying it.")
            elif sys.stdin.isatty() and input("Bind this character and world? [y/N] ").lower() in ("y", "yes"):
                run([sys.executable, ROOT / "scripts/configure-player.py", "--apply"])
            else:
                print("Preview only. To bind explicitly, run python3 scripts/configure-player.py --apply.")
            return
        game = game_path(args.game_dir)
        if args.step == "prepare":
            prepare(args, game)
        elif args.step in ("loader", "bridge"):
            install_stage(args, game)
        else:
            raise SystemExit(check(game, args.python))
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.exit(1, "Setup stopped: " + str(exc) + "\nSee docs/TUTORIAL.md or rerun the same step after resolving this.\n")
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "\nSetup cancelled. Completed steps remain available; rerun to continue.\n")
