#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV="$ROOT/.venv"
CONFIG="$ROOT/agent-hub.config.json"
WITH_EXTENSION=0
SKIP_BACKEND=0
SKIP_DEPS=0
PACKAGE_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-extension) WITH_EXTENSION=1 ;;
    --skip-backend) SKIP_BACKEND=1 ;;
    --skip-deps) SKIP_DEPS=1 ;;
    --package-only) PACKAGE_ONLY=1 ;;
    -h|--help)
      cat <<'HELP'
Usage: sh ./install.sh [options]

Options:
  --with-extension  Also package/install the VS Code extension.
  --skip-backend    Skip Python backend setup.
  --skip-deps       Reuse existing npm dependencies when installing extension.
  --package-only    Build the VSIX but do not install it.
HELP
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if [ "$SKIP_BACKEND" -eq 0 ]; then
  PYTHON=$(find_python || true)
  if [ -z "${PYTHON:-}" ]; then
    echo "Python 3.11 or newer is required. Install Python, then rerun this script." >&2
    exit 1
  fi

  cd "$ROOT"
  if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating .venv..."
    "$PYTHON" -m venv "$VENV"
  fi

  echo "Installing Agent-Hub into .venv..."
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -e "$ROOT"

  if [ ! -f "$CONFIG" ]; then
    echo "Creating agent-hub.config.json..."
    "$VENV/bin/python" -m agent_hub init --with-cloud-examples
  fi

  "$VENV/bin/python" -m agent_hub doctor
fi

if [ "$WITH_EXTENSION" -eq 1 ]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js 20 or newer is required to build/install the VS Code extension." >&2
    exit 1
  fi
  NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
  if [ "$NODE_MAJOR" -lt 20 ]; then
    echo "Node.js 20 or newer is required. Found $(node --version)." >&2
    exit 1
  fi
  EXT_ARGS=""
  if [ "$SKIP_DEPS" -eq 1 ]; then
    EXT_ARGS="$EXT_ARGS --skip-deps"
  fi
  if [ "$PACKAGE_ONLY" -eq 1 ]; then
    EXT_ARGS="$EXT_ARGS --package-only"
  fi
  # shellcheck disable=SC2086
  node "$ROOT/vscode-extension/scripts/install-extension.js" $EXT_ARGS
fi

cat <<EOF

Ready.
Start the server with: sh -c '. .venv/bin/activate && agent-hub serve --watch-inbox'
Open chat with: ./.venv/bin/agent-hub chat --allow-shell-tools
Install the VS Code extension with: sh ./install-extension.sh
Or install backend + extension together with: sh ./install.sh --with-extension
EOF
