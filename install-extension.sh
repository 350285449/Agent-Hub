#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 20 or newer is required to package and install the VS Code extension." >&2
  exit 1
fi
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Node.js 20 or newer is required. Found $(node --version)." >&2
  exit 1
fi
exec node "$ROOT/vscode-extension/scripts/install-extension.js" "$@"
