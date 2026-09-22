"""Domain exceptions for SabiScore backend.

Production inference must never silently replace missing evidence with defaults.
Callers should catch DataUnavailableError and propagate it as a structured gap
(PARTIAL or NO_BET verdict) rather than substituting fabricated values.
"""


class DataUnavailableError(Exception):
    """Raised when required evidence is missing and fail-closed mode is active.

    Propagate to verdict evaluation as PARTIAL (structural gap) or
    NO_BET (reason=DATA_UNAVAILABLE) depending on which evidence is absent.
    """

    def __init__(
        self, message: str, provider: str = "unknown", evidence_type: str = "unknown"
    ):
        super().__init__(message)
        self.provider = provider
        self.evidence_type = evidence_type


class OddsUnavailableError(DataUnavailableError):
    """Raised when 1X2 odds are missing and cannot be fabricated.

    Odds are a required signal — no bet may be surfaced without real market data.
    """

    def __init__(self, provider: str = "unknown"):
        super().__init__(
            "1X2 odds are required but unavailable; cannot fabricate market probabilities",
            provider=provider,
            evidence_type="odds",
        )


class SchemaMismatchError(DataUnavailableError):
    """Raised when a feature vector's width does not match what a consumer expects.

    Zero-padding the missing slots would feed fabricated values into positions
    the model was trained to receive real signal for — the same fabrication
    INV-01/INV-10 forbid for any other evidence type.
    """

    def __init__(
        self, actual_dim: int, expected_dim: int, provider: str = "feature_pipeline"
    ):
        super().__init__(
            f"feature vector has {actual_dim} dimensions, expected {expected_dim}; "
            "refusing to zero-pad the missing values into a live prediction",
            provider=provider,
            evidence_type="schema_mismatch",
        )
        self.actual_dim = actual_dim
        self.expected_dim = expected_dim
