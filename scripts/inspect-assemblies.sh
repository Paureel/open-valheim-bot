#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -eq 0 ]; then echo 'Pass the installed Assembly-CSharp.dll and/or assembly_valheim.dll paths.' >&2; exit 1; fi
exec "$PROJECT_DIR/.tools/dotnet/dotnet" "$PROJECT_DIR/tools/AssemblyInspector/bin/Release/net10.0/AssemblyInspector.dll" "$@"
