#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$PROJECT_DIR/.tools/packages"
curl --fail --location https://dot.net/v1/dotnet-install.sh -o "$PROJECT_DIR/.tools/dotnet-install.sh"
bash "$PROJECT_DIR/.tools/dotnet-install.sh" --version 10.0.401 --architecture arm64 --install-dir "$PROJECT_DIR/.tools/dotnet" --no-path
curl --fail --location https://api.nuget.org/v3-flatcontainer/netstandard.library.ref/2.1.0/netstandard.library.ref.2.1.0.nupkg -o "$PROJECT_DIR/.tools/packages/netstandard.library.ref.2.1.0.nupkg"
