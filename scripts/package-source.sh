#!/bin/sh
# Export committed public files only: no .git history, private state or dependencies.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  echo 'Commit reviewed changes before packaging so the ZIP matches the source.' >&2
  exit 1
fi
mkdir -p .dist
git archive --format=zip --prefix=valheim-ai/ --output=.dist/valheim-ai.zip HEAD
echo 'Created .dist/valheim-ai.zip from committed public files.'
