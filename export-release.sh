#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python "$SCRIPT_DIR/tools/export_release.py" "$@"
