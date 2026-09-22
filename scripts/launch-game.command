#!/bin/sh
# Launch the official Steam installation with the inspected x86_64 mod loader.
# Steam must be running and logged in. No server address or password is stored here.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$PROJECT_DIR/scripts/env.sh"
if /usr/bin/pgrep -x '[Vv]alheim' >/dev/null; then
  echo 'Valheim is already running. Quit that copy before starting the modded launcher.' >&2
  exit 1
fi
GAME_DIR=${VALHEIM_GAME_DIR:-"$HOME/Library/Application Support/Steam/steamapps/common/Valheim"}
if [ ! -f "$GAME_DIR/BepInEx/core/BepInEx.Preloader.dll" ] || [ ! -f "$GAME_DIR/start_game_bepinex.sh" ]; then
  echo 'Install the inspected BepInEx package first.' >&2
  exit 1
fi
if [ ! -d "$GAME_DIR/valheim.app" ]; then
  echo 'Official native Valheim app not found at the configured path.' >&2
  exit 1
fi
cd "$GAME_DIR"
# Temporary macOS assertions live exactly as long as the foreground game process.
# No power preferences or password/lock settings are changed.
exec /usr/bin/caffeinate -di /usr/bin/arch -x86_64 /bin/bash ./start_game_bepinex.sh ./valheim.app
