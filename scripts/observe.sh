#!/bin/sh
set -eu
exec "$(dirname -- "$0")/valheim-codex" observe "$@"
