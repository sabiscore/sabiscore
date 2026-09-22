import pandas as pd
import numpy as np
from typing import Dict, List, Any
import logging

try:
    import shap

    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("SHAP not available, explanations will be limited")

logger = logging.getLogger(__name__)


class ModelExplainer:
    """SHAP-based model explanations"""

    def __init__(self, model=None):
        self.model = model
        self.explainer = None
        self.feature_names = []

    def setup_explainer(
        self, background_data: pd.DataFrame, feature_names: List[str]
    ) -> None:
        """Setup SHAP explainer"""
        if not SHAP_AVAILABLE:
            logger.warning("SHAP not available — explanations disabled (fail-closed)")
            return

        try:
            self.feature_names = feature_names

            # Use a subset of background data for SHAP
            background_sample = background_data.sample(
                min(100, len(background_data)), random_state=42
            )

            # Create explainer based on model type
            if hasattr(self.model, "predict_proba"):
                self.explainer = shap.TreeExplainer(self.model, background_sample)
            else:
                # For ensemble, use the meta model
                if hasattr(self.model, "meta_model"):
                    self.explainer = shap.LinearExplainer(
                        self.model.meta_model, background_sample
                    )
                else:
                    self.explainer = shap.Explainer(self.model, background_sample)

            logger.info("SHAP explainer initialized")

        except Exception as e:
            logger.error(f"Failed to setup SHAP explainer: {e}")
            self.explainer = None

    def explain_prediction(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Generate SHAP explanation for a prediction"""
        try:
            if not SHAP_AVAILABLE or self.explainer is None:
                return self._mock_explanation(features)

            # Calculate SHAP values
            shap_values = self.explainer.shap_values(features)

            # Handle different SHAP output formats
            if isinstance(shap_values, list):
                # Multi-class case
                shap_values_dict = {}
                for i, class_name in enumerate(["home_win", "draw", "away_win"]):
                    shap_values_dict[class_name] = (
                        shap_values[i][0] if len(shap_values[i]) > 0 else []
                    )
            else:
                # Single output
                shap_values_dict = {
                    "prediction": shap_values[0] if len(shap_values) > 0 else []
                }

            # Create explanation
            explanation = {
                "shap_values": shap_values_dict,
                "feature_importance": self._calculate_feature_importance(shap_values),
                "waterfall_data": self._create_waterfall_data(
                    features.iloc[0], shap_values
                ),
                "feature_contributions": self._get_top_contributions(
                    features.iloc[0], shap_values
                ),
            }

            return explanation

        except Exception as e:
            logger.error(f"SHAP explanation failed: {e}")
            return self._mock_explanation(features)

    def _calculate_feature_importance(self, shap_values) -> Dict[str, float]:
        """Calculate global feature importance"""
        try:
            if isinstance(shap_values, list):
                # Average across classes for multi-class
                avg_shap = np.mean([np.abs(sv) for sv in shap_values], axis=0)
            else:
                avg_shap = np.abs(shap_values)

            # Average across samples
            if len(avg_shap.shape) > 1:
                feature_importance = np.mean(avg_shap, axis=0)
            else:
                feature_importance = avg_shap

            # Create feature importance dict
            importance_dict = {}
            for i, feature in enumerate(self.feature_names):
                importance_dict[feature] = (
                    float(feature_importance[i]) if i < len(feature_importance) else 0.0
                )

            # Sort by importance
            sorted_importance = dict(
                sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
            )

            return sorted_importance

        except Exception as e:
            logger.error(f"Feature importance calculation failed: {e}")
            return {}

    def _create_waterfall_data(
        self, features: pd.Series, shap_values
    ) -> Dict[str, Any]:
        """Create waterfall plot data"""
        try:
            base_value = float(self.explainer.expected_value)

            # Get SHAP values for this prediction
            if isinstance(shap_values, list):
                # Use first class for simplicity
                values = (
                    shap_values[0][0]
                    if len(shap_values) > 0 and len(shap_values[0]) > 0
                    else []
                )
            else:
                values = shap_values[0] if len(shap_values) > 0 else []

            # Create contribution data
            contributions = []
            for i, feature in enumerate(self.feature_names):
                if i < len(values):
                    contributions.append(
                        {
                            "feature": feature,
                            "value": float(features[feature]),
                            "shap_value": float(values[i]),
                        }
                    )

            return {"base_value": base_value, "contributions": contributions}

        except Exception as e:
            logger.error(f"Waterfall data creation failed: {e}")
            return {"base_value": 0.33, "contributions": []}

    def _get_top_contributions(
        self, features: pd.Series, shap_values, top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """Get top contributing features"""
        try:
            if isinstance(shap_values, list):
                values = (
                    shap_values[0][0]
                    if len(shap_values) > 0 and len(shap_values[0]) > 0
                    else []
                )
            else:
                values = shap_values[0] if len(shap_values) > 0 else []

            # Create feature contributions
            contributions = []
            for i, feature in enumerate(self.feature_names):
                if i < len(values):
                    contributions.append(
                        {
                            "feature": feature,
                            "contribution": float(values[i]),
                            "feature_value": float(features[feature]),
                        }
                    )

            # Sort by absolute contribution
            contributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)

            return contributions[:top_n]

        except Exception as e:
            logger.error(f"Top contributions calculation failed: {e}")
            return []

    def _mock_explanation(self, features: pd.DataFrame) -> Dict[str, Any]:
        """SHAP unavailable or uninitialized — fail closed with an empty result.

        Zero-fabrication contract: never emit hardcoded feature importances.
        The live caller (services/prediction.py _generate_explanations) treats
        a falsy result as "no SHAP" and falls back to deterministic ranking
        derived from the real validated feature vector.
        """
        logger.info(
            "SHAP explanation unavailable — returning empty result (fail-closed)"
        )
        return {}

    def explain_model_performance(
        self, X_test: pd.DataFrame, y_test: pd.DataFrame
    ) -> Dict[str, Any]:
        """Generate model performance explanations"""
        try:
            if not SHAP_AVAILABLE or self.explainer is None:
                return self._mock_performance_explanation()

            # Calculate SHAP values for test set
            shap_values = self.explainer.shap_values(X_test)

            # Create summary plot data
            summary_data = self._create_summary_plot_data(X_test, shap_values)

            return {
                "summary_plot": summary_data,
                "feature_importance_global": self._calculate_feature_importance(
                    shap_values
                ),
            }

        except Exception as e:
            logger.error(f"Model performance explanation failed: {e}")
            return self._mock_performance_explanation()

    def _create_summary_plot_data(
        self, X: pd.DataFrame, shap_values
    ) -> List[Dict[str, Any]]:
        """Create summary plot data"""
        try:
            # This would create data for a SHAP summary plot
            # Simplified implementation
            summary_data = []

            for feature in self.feature_names:
                feature_data = {
                    "feature": feature,
                    "mean_shap": 0.0,
                    "feature_values": [],
                    "shap_values": [],
                }
                summary_data.append(feature_data)

            return summary_data

        except Exception as e:
            logger.error(f"Summary plot data creation failed: {e}")
            return []

    def _mock_performance_explanation(self) -> Dict[str, Any]:
        """SHAP unavailable — empty performance explanation (fail-closed, zero-fab)."""
        return {"summary_plot": [], "feature_importance_global": {}}
