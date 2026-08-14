import os
import time
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin

from .python_compat import apply_python_314_compat

apply_python_314_compat()

try:
    # Prefer requests if available for easier retries
    import requests
    _HAS_REQUESTS = True
except Exception:
    import urllib.request as _urllib
    _HAS_REQUESTS = False

try:
    import boto3
    _HAS_BOTO3 = True
except Exception:
    _HAS_BOTO3 = False

from ..models.ensemble import SabiScoreEnsemble  # noqa: E402
from .redaction import redact_text, redact_url, safe_endpoint

logger = logging.getLogger(__name__)

MODEL_EXTENSIONS = ('.pkl', '.joblib')
DEFAULT_LEAGUES: tuple[str, ...] = (
    "epl",
    "la_liga",
    "bundesliga",
    "serie_a",
    "ligue_1",
    "eredivisie",
)

# Leagues whose model artifact MUST be present for /health/ready to report ready.
# Deliberately narrower than DEFAULT_LEAGUES (the *load* set): these five are the
# LeaguePolicy CALIBRATED leagues. Eredivisie has a committed v5_phase7 artifact and
# is loaded so its fixtures can be predicted, but its policy is still
# DEFAULT_PENDING_CALIBRATION — a missing Eredivisie artifact must degrade that
# league only, never take the whole service out of rotation.
REQUIRED_LEAGUES: tuple[str, ...] = (
    "epl",
    "la_liga",
    "bundesliga",
    "serie_a",
    "ligue_1",
)

# Keep in sync with scripts/fetch-models.sh
ARTIFACTS = [
    "models/epl_ensemble.pkl",
    "models/serie_a_ensemble.pkl",
    "models/ligue_1_ensemble.pkl",
    "models/la_liga_ensemble.pkl",
    "models/bundesliga_ensemble.pkl",
    "data/processed/epl_training.csv",
    "data/processed/serie_a_training.csv",
    "data/processed/ligue_1_training.csv",
    "data/processed/la_liga_training.csv",
    "data/processed/bundesliga_training.csv",
]


def _download_bytes_with_requests(
    url: str,
    headers: dict,
    timeout: int = 30,
    retries: int = 3,
) -> bytes:
    if not _HAS_REQUESTS:
        raise RuntimeError("requests library is unavailable")
    if retries < 1:
        raise ValueError("retries must be >= 1")

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            logger.warning(
                "Remote model download attempt %s failed for %s: %s",
                attempt,
                redact_url(url),
                redact_text(exc),
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(
        f"Remote model download retries exhausted for {safe_endpoint(url)}"
    )


def _download_bytes_with_urllib(url: str, headers: dict, timeout: int = 30) -> bytes:
    req = _urllib.Request(url)
    for key, value in headers.items():
        req.add_header(key, value)
    with _urllib.urlopen(req, timeout=timeout) as response:
        return response.read()


def _resolve_local_artifact(
    artifact_name: str,
    local_model_dirs: Sequence[Path],
) -> Optional[Path]:
    for model_dir in local_model_dirs:
        candidate = model_dir / artifact_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _smoke_test_ensemble_model(model: Any, league: str, artifact_name: str) -> None:
    if not getattr(model, "is_trained", False):
        raise RuntimeError(f"Loaded model is not trained: {artifact_name}")

    feature_columns = list(getattr(model, "feature_columns", []) or [])
    if not feature_columns:
        raise RuntimeError(f"Model missing feature columns metadata: {artifact_name}")

    import pandas as pd

    row = {name: 0.0 for name in feature_columns}
    frame = pd.DataFrame([row])
    prediction = model.predict(frame)

    expected_columns = {"home_win_prob", "draw_prob", "away_win_prob"}
    prediction_columns = set(getattr(prediction, "columns", []))
    if not expected_columns.issubset(prediction_columns):
        raise RuntimeError(
            f"Smoke test failed for {league}: missing prediction columns "
            f"{sorted(expected_columns - prediction_columns)}"
        )


def _force_single_thread_inference(obj: Any, *, _seen: set[int] | None = None) -> None:
    """Best-effort guard against joblib worker-pool creation during inference."""

    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return
    _seen.add(obj_id)

    if hasattr(obj, "n_jobs"):
        try:
            setattr(obj, "n_jobs", 1)
        except Exception:
            pass

    if isinstance(obj, dict):
        iterable = obj.values()
    elif isinstance(obj, (list, tuple, set)):
        iterable = obj
    else:
        iterable = []
        for attr in ("models", "estimators_", "estimators", "base_estimators", "steps", "named_steps", "meta_model"):
            try:
                value = getattr(obj, attr)
            except Exception:
                continue
            if value is not None:
                iterable = [*iterable, value]

    for child in iterable:
        _force_single_thread_inference(child, _seen=_seen)


def _load_model_from_bytes(payload: bytes) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=True) as tmp_file:
        tmp_file.write(payload)
        tmp_file.flush()
        return SabiScoreEnsemble.load_model(tmp_file.name)


def load_ensemble_per_league(
    model_base_url: Optional[str],
    version: str,
    local_model_dirs: Sequence[Path],
    leagues: Sequence[str] = DEFAULT_LEAGUES,
    fetch_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Load one validated ensemble per league.

    Resolution order:
    1) Remote artifact at MODEL_BASE_URL/{league}_ensemble_{version}.pkl (if MODEL_BASE_URL is set)
    2) Local artifact from provided local_model_dirs

    Raises RuntimeError/FileNotFoundError when any required league artifact cannot be loaded
    or fails smoke-test inference.
    """
    headers: dict[str, str] = {}
    if fetch_token:
        headers["Authorization"] = f"Bearer {fetch_token}"

    normalized_dirs = [Path(path) for path in local_model_dirs]
    loaded_models: Dict[str, Any] = {}

    for league in leagues:
        artifact_name = f"{league}_ensemble_{version}.pkl"
        model = None

        if model_base_url:
            remote_url = urljoin(model_base_url.rstrip("/") + "/", artifact_name)
            try:
                logger.info("Loading remote model artifact %s", artifact_name)
                if _HAS_REQUESTS:
                    payload = _download_bytes_with_requests(remote_url, headers)
                else:
                    payload = _download_bytes_with_urllib(remote_url, headers)
                model = _load_model_from_bytes(payload)
            except Exception as exc:
                logger.warning(
                    "Remote model unavailable for %s (%s). Falling back to local artifact.",
                    league,
                    redact_text(exc),
                )

        if model is None:
            local_artifact = _resolve_local_artifact(artifact_name, normalized_dirs)
            if local_artifact is None:
                searched = ", ".join(str(path / artifact_name) for path in normalized_dirs)
                raise FileNotFoundError(
                    f"Missing model artifact for league '{league}': {artifact_name}. "
                    f"Set MODEL_BASE_URL or ensure one of these exists: {searched}"
                )

            logger.info("Loading local model artifact %s", local_artifact)
            model = SabiScoreEnsemble.load_model(str(local_artifact))

        _force_single_thread_inference(model)
        _smoke_test_ensemble_model(model, league=league, artifact_name=artifact_name)
        loaded_models[str(league)] = model

    return loaded_models


def _env_flag(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).lower() in ('true', '1', 'yes')


def _find_valid_models(models_dir: str) -> List[str]:
    valid_models: List[str] = []
    try:
        existing = [f for f in os.listdir(models_dir) if f.endswith(MODEL_EXTENSIONS)]
    except Exception:
        return valid_models

    for fname in existing:
        path = os.path.join(models_dir, fname)
        try:
            if os.path.getsize(path) >= 10_240:
                valid_models.append(fname)
        except Exception:
            continue
    return valid_models


def _download_with_requests(url: str, dest: str, headers: dict, timeout: int = 10, retries: int = 3) -> None:
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            resp.raise_for_status()
            with open(dest, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
            return
        except Exception as e:
            logger.warning(
                "Download attempt %s failed for %s: %s",
                attempt,
                redact_url(url),
                redact_text(e),
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise


def _download_with_urllib(url: str, dest: str, headers: dict, timeout: int = 10) -> None:
    req = _urllib.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    with _urllib.urlopen(req, timeout=timeout) as resp:
        with open(dest, 'wb') as fh:
            fh.write(resp.read())


def fetch_models_if_needed(model_base_url: Optional[str], dest_root: str, fetch_token: Optional[str] = None) -> bool:
    """Ensure model artifacts exist under dest_root/models. If missing and model_base_url is provided,
    attempt to download artifacts. Returns True if artifacts exist after this call, False otherwise.
    """
    models_dir = os.path.join(dest_root, 'models')
    os.makedirs(models_dir, exist_ok=True)

    skip_s3 = _env_flag('SKIP_S3')
    model_fetch_strict = _env_flag('MODEL_FETCH_STRICT')

    # Check for existing .pkl files of reasonable size
    valid_models = _find_valid_models(models_dir)

    if valid_models:
        logger.info(f"Found {len(valid_models)} valid local model(s): {', '.join(valid_models)}")
        logger.info("Model artifacts loaded successfully from local storage")
        return True

    if skip_s3:
        logger.warning("SKIP_S3=true: Model fetching disabled, no valid local models found")
        return not model_fetch_strict

    if not model_base_url:
        logger.warning("No MODEL_BASE_URL set and no valid models present")
        if model_fetch_strict:
            logger.error("MODEL_FETCH_STRICT=true: Failing due to missing models")
            return False
        logger.info("MODEL_FETCH_STRICT=false: Continuing without remote fetch")
        return True

    # Support s3:// URIs or https:// endpoints
    if not (model_base_url.startswith('https://') or model_base_url.startswith('s3://')):
        logger.error("MODEL_BASE_URL must use https:// or s3://")
        return False

    headers = {}
    if fetch_token:
        headers['Authorization'] = f"Bearer {fetch_token}"

    logger.info(
        "Fetching model artifacts from %s into configured destination",
        safe_endpoint(model_base_url),
    )

    for rel in ARTIFACTS:
        dest = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        # If model_base_url is an S3 URI, prefer using boto3
        if model_base_url.startswith('s3://'):
            if not _HAS_BOTO3:
                logger.error("MODEL_BASE_URL is s3:// but boto3 is not installed")
                return False

            # parse s3://bucket/path_prefix
            _, _, bucket_and_prefix = model_base_url.partition('s3://')
            bucket_and_prefix = bucket_and_prefix.rstrip('/')
            # bucket_and_prefix may be bucket or bucket/prefix
            parts = bucket_and_prefix.split('/', 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ''
            key = f"{prefix}/{rel}" if prefix else rel
            key = key.lstrip('/')
            logger.info("Downloading S3 model artifact %s", rel)
            try:
                s3 = boto3.client('s3')
                # use streaming download
                with open(dest, 'wb') as fh:
                    s3.download_fileobj(bucket, key, fh)
            except Exception as e:
                logger.error(
                    "Failed to download S3 model artifact %s: %s",
                    rel,
                    redact_text(e),
                )
                return False

        else:
            url = urljoin(model_base_url.rstrip('/') + '/', rel)
            logger.info("Downloading HTTPS model artifact %s", rel)
            try:
                if _HAS_REQUESTS:
                    _download_with_requests(url, dest, headers)
                else:
                    _download_with_urllib(url, dest, headers)
            except Exception as e:
                logger.error(
                    "Failed to download HTTPS model artifact %s from %s: %s",
                    rel,
                    safe_endpoint(url),
                    redact_text(e),
                )
                return False

    logger.info("All artifacts downloaded (subject to validation).")
    return True
