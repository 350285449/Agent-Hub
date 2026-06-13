#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INCLUDE_EXTENSION=0
INCLUDE_OPTIONAL=0
JSON=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --include-extension) INCLUDE_EXTENSION=1 ;;
    --include-optional) INCLUDE_OPTIONAL=1 ;;
    --json) JSON=1 ;;
    -h|--help)
      cat <<'HELP'
Usage: sh ./scripts/check-requirements.sh [options]

Options:
  --include-extension  Also check Node.js, npm, and a VS Code-compatible CLI.
  --include-optional   Also check Ollama and Codex CLI.
  --json               Print machine-readable JSON.
HELP
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

rows=""
missing_required=0

add_row() {
  name=$1
  id=$2
  ok=$3
  required=$4
  version=$5
  detail=$6
  fix=$7
  url=$8

  if [ "$required" = "true" ] && [ "$ok" != "true" ]; then
    missing_required=$((missing_required + 1))
  fi

  if [ "$JSON" -eq 1 ]; then
    row=$(printf '{"name":"%s","id":"%s","ok":%s,"required":%s,"version":"%s","detail":"%s","install":"%s","url":"%s"}' \
      "$(json_escape "$name")" \
      "$(json_escape "$id")" \
      "$ok" \
      "$required" \
      "$(json_escape "$version")" \
      "$(json_escape "$detail")" \
      "$(json_escape "$fix")" \
      "$(json_escape "$url")")
    if [ -z "$rows" ]; then
      rows=$row
    else
      rows="$rows,$row"
    fi
  else
    status="OK"
    if [ "$ok" != "true" ]; then
      if [ "$required" = "true" ]; then
        status="MISSING"
      else
        status="OPTIONAL"
      fi
    fi
    printf '%-9s %-18s %-14s %s\n' "$status" "$name" "$version" "$detail"
    if [ "$ok" != "true" ]; then
      printf '          Install: %s\n' "$fix"
      printf '          Download: %s\n' "$url"
    fi
  fi
}

python_found=0
python_version=""
python_label=""
for candidate in "$ROOT/.venv/bin/python" "$ROOT/.venv-check/bin/python" python3 python; do
  if { [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; }; then
    if version=$("$candidate" -c "import sys, venv; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null); then
      python_found=1
      python_version=$version
      python_label=$candidate
      break
    fi
  fi
done

if [ "$JSON" -eq 0 ]; then
  echo "Agent Hub requirement check"
  echo ""
fi

if [ "$python_found" -eq 1 ]; then
  add_row "Python 3.11+" "python" "true" "true" "$python_version" "Found with: $python_label" "Install Python 3.11+ with your OS package manager." "https://www.python.org/downloads/"
else
  add_row "Python 3.11+" "python" "false" "true" "" "Required for the Agent Hub backend and venv setup." "Install Python 3.11+ with your OS package manager." "https://www.python.org/downloads/"
fi

if [ "$INCLUDE_EXTENSION" -eq 1 ]; then
  if command -v node >/dev/null 2>&1; then
    node_version=$(node -p "process.versions.node" 2>/dev/null || true)
    node_major=$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)
    if [ "${node_major:-0}" -ge 20 ] 2>/dev/null; then
      add_row "Node.js 20+" "node" "true" "true" "$node_version" "Found on PATH." "Install Node.js LTS." "https://nodejs.org/en/download"
    else
      add_row "Node.js 20+" "node" "false" "true" "$node_version" "Found an older Node.js; Agent Hub needs 20+." "Install Node.js LTS." "https://nodejs.org/en/download"
    fi
  else
    add_row "Node.js 20+" "node" "false" "true" "" "Required to package/install the VS Code extension." "Install Node.js LTS." "https://nodejs.org/en/download"
  fi

  if command -v npm >/dev/null 2>&1; then
    add_row "npm" "npm" "true" "true" "$(npm --version 2>/dev/null || true)" "Found on PATH." "Install Node.js LTS." "https://nodejs.org/en/download"
  else
    add_row "npm" "npm" "false" "true" "" "Required for extension packaging and Codex CLI installation." "Install Node.js LTS." "https://nodejs.org/en/download"
  fi

  code_ok=false
  code_version=""
  code_label=""
  for candidate in code code-insiders codium; do
    if command -v "$candidate" >/dev/null 2>&1; then
      code_version=$("$candidate" --version 2>/dev/null | sed -n '1p' || true)
      code_label=$candidate
      code_ok=true
      break
    fi
  done
  if [ "$code_ok" = "true" ]; then
    add_row "VS Code CLI" "vscode_cli" "true" "true" "$code_version" "Found with: $code_label" "Install VS Code or enable its shell command." "https://code.visualstudio.com/download"
  else
    add_row "VS Code CLI" "vscode_cli" "false" "true" "" "Required to install the VSIX from scripts." "Install VS Code or enable its shell command." "https://code.visualstudio.com/download"
  fi
fi

if [ "$INCLUDE_OPTIONAL" -eq 1 ]; then
  if command -v ollama >/dev/null 2>&1; then
    add_row "Ollama" "ollama" "true" "false" "$(ollama --version 2>/dev/null | sed -n '1p' || true)" "Found on PATH." "Install Ollama Desktop." "https://ollama.com/download"
  else
    add_row "Ollama" "ollama" "false" "false" "" "Optional local-model runtime." "Install Ollama Desktop." "https://ollama.com/download"
  fi

  if command -v codex >/dev/null 2>&1; then
    add_row "Codex CLI" "codex_cli" "true" "false" "$(codex --version 2>/dev/null | sed -n '1p' || true)" "Found on PATH." "npm install -g @openai/codex@latest" "https://www.npmjs.com/package/@openai/codex"
  else
    add_row "Codex CLI" "codex_cli" "false" "false" "" "Optional no-key Codex routing helper." "npm install -g @openai/codex@latest" "https://www.npmjs.com/package/@openai/codex"
  fi
fi

if [ "$JSON" -eq 1 ]; then
  ok=false
  if [ "$missing_required" -eq 0 ]; then
    ok=true
  fi
  printf '{"object":"agent_hub.requirements","ok":%s,"include_extension":%s,"include_optional":%s,"requirements":[%s]}\n' \
    "$ok" \
    "$( [ "$INCLUDE_EXTENSION" -eq 1 ] && echo true || echo false )" \
    "$( [ "$INCLUDE_OPTIONAL" -eq 1 ] && echo true || echo false )" \
    "$rows"
fi

if [ "$missing_required" -gt 0 ]; then
  if [ "$JSON" -eq 0 ]; then
    echo ""
    echo "Install the missing required item(s), reopen your terminal if PATH changed, then rerun the installer."
  fi
  exit 1
fi
