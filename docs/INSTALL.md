# Installation reference

Start with the [first-play tutorial](TUTORIAL.md). The setup assistant
can be opened by double-clicking `setup.command`, or run from the repository root:

| Command | What it does |
|---|---|
| `./setup.command prepare` | Detects Steam game files, verifies reviewed hashes, stages the pinned loader, installs the local SDK and OpenJev environment/model, builds the plugin, initializes private state |
| `./setup.command loader` | Installs backed-up BepInEx files, after normal manual play and with Valheim closed |
| `./setup.command bridge` | Rebuilds and installs the two bridge DLLs, after a successful BepInEx launch and with Valheim closed |
| `./setup.command player` | Displays the loaded character/world and asks whether to bind that identity locally |
| `./setup.command check` | Read-only local file/prerequisite checklist; does not start a model or game |

`--dry-run` previews an installation step without downloads or changes. Prerequisite
validation still runs, so missing or unsupported game/Python files can stop a preview.
`--normal-play-verified` supplies the loader/bridge step's manual-play confirmation
for noninteractive use. It does not bypass the running-game guard or assembly checks.

## Custom locations

```sh
./setup.command prepare --game-dir '/Volumes/Games/steamapps/common/Valheim' \
  --python '/opt/homebrew/bin/python3.12'
```

The game folder is saved in ignored `.tools/game-dir`; the build and launch scripts
reuse it. `VALHEIM_GAME_DIR` or `--game-dir` overrides it. `VALHEIM_PYTHON` overrides
the launcher interpreter. The setup assistant discovers native Steam libraries,
but asks for an explicit path when more than one installation exists. The folder
must contain the official `valheim.app`, not a Windows/Whisky installation.

Finder launchers discover Codex on PATH, in `~/.local/bin`, or bundled with the
ChatGPT/Codex apps. The OpenJev virtual environment supplies the Python runtime
after preparation. Keep the repository in its installed location; after moving it,
move the old `.tools/system-one` folder aside and rerun preparation with native
Python 3.12 because Python virtual environments are not relocatable.

## Versions and downloads

| Dependency | Pinned/required value |
|---|---|
| Game bindings | Valheim 1.0.15, Steam build 25390630; `bridge/Plugin/reviewed-assemblies.json` |
| BepInEx Valheim pack | 5.4.2350 from [Thunderstore](https://thunderstore.io/c/valheim/p/denikson/BepInExPack_Valheim/versions) |
| BepInEx ZIP SHA-256 | `37a91c000b4e88f2ed7a4bd7d812239852d2e36cbf0ff0a9f5faacfba46b105f` |
| Local .NET SDK | 10.0.401 arm64, downloaded from Microsoft by `bootstrap-toolchain.sh` |
| Python | Native arm64 3.12 for OpenJev; gateway code supports 3.9+ |
| Model/runtime | OpenJev 0.8B pinned revision/hash in `setup-system-one.py`; dependencies in `requirements-system-one.txt` |
| Planner | `gpt-5.6-luna`, reasoning `low`; no silent fallback |

Preparation needs internet and several GB of free space. Only the OpenJev weights
are about 1.7 GB; the SDK, Python packages and run journals need additional room.
It checks the game before downloading and verifies the BepInEx archive before
extracting it. A changed game build is rejected; updating hashes alone is not an
adapter port. Re-inspect affected APIs and bindings after a game update.

The installer preserves existing private configuration. Loader and bridge changes
are backed up with manifests. It leaves Steam launch options unchanged, and does
not change security settings, code signatures, or quarantine flags. A pre-existing
BepInEx install is left in place by the assistant; verify its compatibility before
using the bridge step.

## Local state and privacy

| Content | Location |
|---|---|
| Tools, model, staged loader | `.tools/` in this checkout, ignored by Git |
| Built plugin/core | `build/`, ignored by Git |
| Private settings, character, trust lists | `~/Library/Application Support/ValheimCodex/` |
| Memory | Same folder: `memory.sqlite3` |
| Logs and run journals | Same folder: `logs/` and `playtests/` |
| Backups | Same folder: `backups/` |
| Gameplay Codex sessions | Same folder: `codex/` |
| Live brain feed | Same folder: `run/brain.json` |
| BepInEx startup log | `<Valheim>/BepInEx/LogOutput.log` |

The bridge/gateway bind only to `127.0.0.1:8731` and `:8732`, require private bearer
tokens, and reject unexpected origins/hosts. The read-only observer uses `:8733`.
No server address or password is needed by setup. Keep raw journals private: they
can contain game screenshots and dialogue. Luna receives images/dialogue through
Codex during autonomous play; OpenJev inference stays local.

## Optional Codex MCP integration

Standalone gameplay does not need MCP registration. To expose the local service
to your operator Codex environment, run after preparation:

```sh
.tools/system-one/bin/python scripts/install-local.py
```

This backs up the Codex configuration, registers only the `valheim-codex` entry,
and refuses to replace an unrelated entry with that name. Reload the operator's
MCP connections afterward. Existing unrelated entries are preserved. The gameplay
planner itself has tool execution disabled.

## Uninstall or restore

Stop the controller and quit Valheim before removing installed files:

```sh
./scripts/stop.sh
.tools/system-one/bin/python scripts/uninstall.py
```

This unregisters this project's MCP entry if present, requests service shutdown,
restores bridge files from installation backups and keeps private memories,
settings, logs and backups. It preserves files changed after installation.
Use `--include-bepinex` only if you also want to reverse the loader installation;
other mods may depend on it. Remove any Steam launch options you added yourself.
To restore one particular installation:

```sh
.tools/system-one/bin/python scripts/restore-install.py '/path/to/backup/manifest.json'
```

After services and game are stopped, removing the repository deletes its local
dependencies. Private state remains in Application Support until you choose to
remove it separately. The project's default uninstall does not delete Valheim,
Steam, your worlds, or your characters.
