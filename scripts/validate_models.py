#!/usr/bin/env python3
"""
scripts/validate_models.py

Simple validator for joblib model artifacts. Intended for CI / deploy checks.

Usage:
  python scripts/validate_models.py --models-dir ./models --timeout 10

Exits with status 0 when all .pkl files load successfully within timeout.
Exits with non-zero when any file fails validation.
"""
import argparse
import hashlib
import os
import sys
import json
from multiprocessing import Process, Pipe


def _worker_load(path, conn):
    """Attempt to load a joblib file and report result to parent via pipe."""
    try:
        import joblib
        obj = joblib.load(path)
        # basic sanity: ensure it's a dict-like with expected keys or an ensemble instance
        meta = {'type': type(obj).__name__, 'ok': False, 'has_dummy': False, 'model_types': []}

        # Normalize to a dict-like structure for inspection
        try:
            if isinstance(obj, dict):
                models = obj.get('models')
                meta_model = obj.get('meta_model')
            else:
                models = getattr(obj, 'models', None)
                meta_model = getattr(obj, 'meta_model', None)

            # collect model type names
            if isinstance(models, dict):
                for k, m in models.items():
                    try:
                        meta['model_types'].append(type(m).__name__)
                    except Exception:
                        meta['model_types'].append('Unknown')

            if meta_model is not None:
                meta['model_types'].append(type(meta_model).__name__)

            # detect DummyClassifier presence
            try:
                from sklearn.dummy import DummyClassifier
                # check meta_model and base models
                if isinstance(meta_model, DummyClassifier):
                    meta['has_dummy'] = True
                if isinstance(models, dict):
                    for m in models.values():
                        if isinstance(m, DummyClassifier):
                            meta['has_dummy'] = True
            except Exception:
                # sklearn may not be available in minimal CI; ignore detection then
                pass

            meta['ok'] = True
        except Exception:
            meta['ok'] = False

        conn.send({'ok': True, 'meta': meta})
    except Exception as e:
        conn.send({'ok': False, 'error': repr(e)})
    finally:
        conn.close()


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_file(path, timeout):
    parent_conn, child_conn = Pipe()
    p = Process(target=_worker_load, args=(path, child_conn))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return {'ok': False, 'error': f'timeout after {timeout}s'}

    if parent_conn.poll():
        result = parent_conn.recv()
        return result
    return {'ok': False, 'error': 'no response from worker'}


def main(models_dir: str, timeout: int = 10):
    if not os.path.isdir(models_dir):
        print(f"Models directory not found: {models_dir}")
        return 2

    pkl_files = [f for f in os.listdir(models_dir) if f.endswith('.pkl')]
    if not pkl_files:
        print(f"No .pkl files found in {models_dir}")
        return 1

    failures = []
    summary = []
    for fname in sorted(pkl_files):
        path = os.path.join(models_dir, fname)
        size = os.path.getsize(path)
        sha = sha256_of_file(path)
        print(f"Validating {fname} (size={size} bytes, sha256={sha})...")
        res = validate_file(path, timeout)
        if not res.get('ok'):
            print(f"  FAILED: {res.get('error')}")
            failures.append({'file': fname, 'error': res.get('error')})
        else:
            meta = res.get('meta') or {}
            extra = ''
            if meta.get('has_dummy'):
                extra = ' (contains DummyClassifier)'
                print(f"  WARNING: file contains DummyClassifier - consider replacing with production model{extra}")
            else:
                print(f"  OK: type={meta.get('type')} ok={meta.get('ok')}")
        summary.append({'file': fname, 'size': size, 'sha256': sha, 'result': res})

    # write summary artifact
    out_path = os.path.join(models_dir, 'validation-summary.json')
    with open(out_path, 'w') as f:
        json.dump({'summary': summary, 'failures': failures}, f, indent=2)

    # If any file contains DummyClassifier, treat as failure in CI by default
    dummy_files = [s for s in summary if s['result'].get('meta', {}).get('has_dummy')]
    if failures or dummy_files:
        if dummy_files and not os.environ.get('ALLOW_DUMMY_MODELS'):
            print(f"\nValidation finished: {len(failures)} failures and {len(dummy_files)} dummy-model files detected. See {out_path} for details.")
            return 4
        if failures:
            print(f"\nValidation finished: {len(failures)} failures. See {out_path} for details.")
            return 3
        # dummy_files present but ALLOW_DUMMY_MODELS set
        print(f"\nValidation finished: {len(summary)} files OK, but {len(dummy_files)} dummy-model files detected (ALLOW_DUMMY_MODELS=1). Summary written to {out_path}")
        return 0

    print(f"\nValidation finished: all {len(pkl_files)} files OK. Summary written to {out_path}")
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models-dir', default=os.path.join(os.getcwd(), 'models'), help='Path to models directory')
    parser.add_argument('--timeout', type=int, default=10, help='Seconds to wait for each model load')
    args = parser.parse_args()
    code = main(args.models_dir, args.timeout)
    sys.exit(code)
