# Sourced by launchers; PROJECT_DIR must already be set.
# Finder does not inherit the user's interactive shell PATH.
PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
if ! command -v codex >/dev/null 2>&1; then
  for CODEX_APP_DIR in /Applications/ChatGPT.app /Applications/Codex.app "$HOME/Applications/ChatGPT.app" "$HOME/Applications/Codex.app"; do
    if [ -x "$CODEX_APP_DIR/Contents/Resources/codex" ]; then
      PATH="$PATH:$CODEX_APP_DIR/Contents/Resources"
      break
    fi
  done
fi
export PATH
if [ -z "${VALHEIM_GAME_DIR:-}" ] && [ -f "$PROJECT_DIR/.tools/game-dir" ]; then
  IFS= read -r VALHEIM_GAME_DIR < "$PROJECT_DIR/.tools/game-dir" || true
  export VALHEIM_GAME_DIR
fi
if [ -n "${VALHEIM_PYTHON:-}" ]; then
  PLAYER_PYTHON="$VALHEIM_PYTHON"
elif [ -x "$PROJECT_DIR/.tools/system-one/bin/python" ]; then
  PLAYER_PYTHON="$PROJECT_DIR/.tools/system-one/bin/python"
else
  PLAYER_PYTHON=$(command -v python3.12 || command -v python3 || true)
fi
if [ -z "$PLAYER_PYTHON" ]; then
  echo 'Python is missing. Install native Python 3.12; see docs/TUTORIAL.md.' >&2
  exit 1
fi
