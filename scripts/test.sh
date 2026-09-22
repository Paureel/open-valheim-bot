#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
"$PROJECT_DIR/scripts/build.sh"
"$PROJECT_DIR/.tools/dotnet/dotnet" bridge/Harness/bin/Release/net10.0/ValheimCodexBridge.Harness.dll
PYTHONPATH="$PROJECT_DIR/src" /usr/bin/python3 -m unittest discover -s tests -v
