#!/usr/bin/env sh
set -eu

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "CodexRecall needs Python 3.10 or newer. Install it with your system package manager, then rerun this script." >&2
  exit 1
fi

SCRIPT_DIR=""
if [ -f "$0" ]; then
  SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
fi
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
  SOURCE="$SCRIPT_DIR"
else
  SOURCE="https://github.com/IamAngusU/CodexRecall/archive/refs/heads/main.zip"
fi

echo "Installing CodexRecall with $PYTHON from $SOURCE"
"$PYTHON" -m pip install --user --upgrade "$SOURCE"
echo "Installed. Run: $PYTHON -m codex_recall"
