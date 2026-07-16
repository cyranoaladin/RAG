#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import importlib.metadata as md

import numpy
import pandas
import pyarrow
import streamlit
import tornado
import watchdog
from google import protobuf

expected = {
    "streamlit": "1.39.0",
    "pyarrow": "24.0.0",
    "pandas": "2.2.3",
    "numpy": "1.26.4",
    "protobuf": "5.29.6",
    "tornado": "6.5.7",
    "watchdog": "5.0.3",
}

for package, expected_version in expected.items():
    actual = md.version(package)
    print(f"{package}={actual}")
    if actual != expected_version:
        raise SystemExit(
            f"{package} version mismatch: expected {expected_version}, got {actual}"
        )

print("UI_RUNTIME_IMPORTS_OK")
PY
