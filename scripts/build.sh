#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$PROJECT_DIR/scripts/env.sh"
cd "$PROJECT_DIR"
export DOTNET_CLI_HOME="$PROJECT_DIR/.tools/dotnet-home"
export NUGET_PACKAGES="$PROJECT_DIR/.tools/nuget"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
DOTNET_EXE="$PROJECT_DIR/.tools/dotnet/dotnet"
if [ ! -x "$DOTNET_EXE" ]; then DOTNET_EXE=$(command -v dotnet || true); fi
if [ -z "$DOTNET_EXE" ]; then echo 'Install .NET 10 SDK or run scripts/bootstrap-toolchain.sh.' >&2; exit 1; fi
"$DOTNET_EXE" build bridge/Core -c Release --nologo -p:UseSharedCompilation=false
"$DOTNET_EXE" build bridge/Harness -c Release --nologo -p:UseSharedCompilation=false
"$DOTNET_EXE" build tools/AssemblyInspector -c Release --nologo -p:UseSharedCompilation=false
mkdir -p build
cp bridge/Core/bin/Release/netstandard2.1/ValheimCodexBridge.Core.dll build/
if [ "${1:-}" = '--plugin' ]; then
  GAME_DIR=${VALHEIM_GAME_DIR:-"$HOME/Library/Application Support/Steam/steamapps/common/Valheim"}
  VALHEIM_MANAGED_DIR=${VALHEIM_MANAGED_DIR:-"$GAME_DIR/valheim.app/Contents/Resources/Data/Managed"}
  VALHEIM_BEPINEX_DIR=${VALHEIM_BEPINEX_DIR:-"$PROJECT_DIR/.tools/bepinex-staged/BepInExPack_Valheim/BepInEx"}
  "$PLAYER_PYTHON" scripts/verify-bindings.py "$VALHEIM_MANAGED_DIR"
  "$DOTNET_EXE" build bridge/Plugin -c Release --nologo "-p:ManagedDir=$VALHEIM_MANAGED_DIR" "-p:BepInExDir=$VALHEIM_BEPINEX_DIR"
  cp bridge/Plugin/bin/Release/netstandard2.1/ValheimCodexBridge.dll build/
  echo 'Game plugin compiled against reviewed native Valheim assemblies. In-game acceptance still required.'
else
  echo 'Core, simulation harness, and assembly inspector built. Game plugin requires installed references.'
fi
