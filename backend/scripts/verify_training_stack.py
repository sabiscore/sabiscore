"""Verify the isolated offline model-research environment.

This check proves importability only. It does not certify a candidate model,
clear the real-settlement gate, or change the active generation.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


# SHAP imports matplotlib. Keep its cache in an ignored, writable project path so
# the verifier works in restricted CI/worktree environments without touching the
# user's profile directory.
os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".cache" / "matplotlib"))


PACKAGES = {
    "catboost": "catboost",
    "evidently": "evidently",
    "great_expectations": "great-expectations",
    "lightgbm": "lightgbm",
    "mlflow": "mlflow",
    "optuna": "optuna",
    "shap": "shap",
    "sklearn": "scikit-learn",
    "xgboost": "xgboost",
}


def main() -> None:
    if sys.version_info >= (3, 14):
        raise SystemExit(
            "The offline training stack is supported on Python 3.11-3.13; "
            "use the API-only dependency branch on Python 3.14"
        )

    failures: dict[str, str] = {}
    versions: dict[str, str] = {}
    for module_name, distribution_name in PACKAGES.items():
        try:
            importlib.import_module(module_name)
            versions[distribution_name] = version(distribution_name)
        except (ImportError, PackageNotFoundError) as exc:
            failures[distribution_name] = type(exc).__name__

    report = {
        "certification": "IMPORTABILITY_ONLY",
        "failures": failures,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": versions,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
