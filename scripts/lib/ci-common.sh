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

require_node_2222() {
    local node_bin="${1:-}"
    local node_version
    local major
    local minor

    if [ -z "$node_bin" ] \
        || ! node_version="$("$node_bin" --version 2>/dev/null)" \
        || [[ ! "$node_version" =~ ^v([0-9]+)\.([0-9]+)\.[0-9]+$ ]]; then
        echo "ERROR: Node 22.22+ is required" >&2
        return 1
    fi

    major="${BASH_REMATCH[1]}"
    minor="${BASH_REMATCH[2]}"
    if ((10#$major < 22 || (10#$major == 22 && 10#$minor < 22))); then
        echo "ERROR: Node 22.22+ is required" >&2
        return 1
    fi
}

run_checked() {
    "$@"
}
