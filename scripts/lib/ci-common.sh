#!/usr/bin/env bash

require_python_311() {
    local python_bin="${1:-}"

    if [ -z "$python_bin" ] || ! "$python_bin" -c \
        'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
        2>/dev/null; then
        echo "ERROR: Python 3.11+ is required" >&2
        return 1
    fi
}

run_checked() {
    "$@"
}
