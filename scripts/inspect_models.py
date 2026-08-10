#!/usr/bin/env python3
"""Inspect joblib model artifacts and print a usability report.

Usage:
  python scripts/inspect_models.py models/epl_ensemble.pkl models/bundesliga_ensemble.pkl

This will attempt to load each file, report its structure, key contents, metadata, and
perform a lightweight smoke test (shape of feature_columns and a dummy predict_proba if possible).
"""
import sys
import json
from pathlib import Path


def inspect(path):
    try:
        import joblib
    except Exception as e:
        return {"error": f"joblib import failed: {e}"}

    out = {"file": str(path)}
    if not Path(path).exists():
        out["error"] = "file not found"
        return out

    try:
        obj = joblib.load(path)
    except Exception as e:
        out["error"] = f"load error: {e!r}"
        return out

    out["type"] = type(obj).__name__

    # If it's a dict-like artifact (our expected format)
    try:
        if isinstance(obj, dict):
            keys = list(obj.keys())
            out["keys"] = keys
            # models
            models = obj.get("models")
            if models is not None:
                out["base_model_names"] = list(models.keys())
                out["base_model_count"] = len(models)
            meta = obj.get("meta_model")
            if meta is not None:
                out["meta_model_type"] = type(meta).__name__
            fc = obj.get("feature_columns")
            if fc is not None:
                out["feature_columns_count"] = len(fc)
                out["feature_columns_sample"] = fc[:10]
            mm = obj.get("model_metadata")
            if mm is not None:
                # include a couple of keys people care about
                out["model_metadata_keys"] = list(mm.keys())
                for k in ("trained_at", "accuracy", "brier_score", "log_loss"):
                    if k in mm:
                        out[k] = mm.get(k)

            out["is_trained"] = bool(obj.get("is_trained"))

            # Try a tiny predict_proba smoke test using meta model if possible
            try:
                import numpy as np
                if meta is not None and hasattr(meta, 'predict_proba') and fc is not None and len(fc) > 0:
                    # create a single-row dummy input of zeros with expected feature count
                    X = np.zeros((1, len(fc)))
                    probs = meta.predict_proba(X)
                    out["meta_predict_proba_shape"] = getattr(probs, 'shape', str(type(probs)))
            except Exception as e:
                out.setdefault("notes", []).append(f"meta predict_proba failed: {e}")

        else:
            out["info"] = "artifact is not a dict, raw type returned"
    except Exception as e:
        out["error"] = f"inspection error: {e!r}"

    return out


def main(args):
    paths = args[1:] or ["models"]
    reports = []
    for p in paths:
        reports.append(inspect(p))

    print(json.dumps(reports, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv)
