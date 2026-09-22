#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$PROJECT_DIR/scripts/env.sh"
export PYTHONDONTWRITEBYTECODE=1
cd "$PROJECT_DIR"
exec "$PLAYER_PYTHON" scripts/setup.py "$@"
