import re

with open('backend/src/models/ensemble.py', 'r', encoding='utf-8') as f:
    code = f.read()

new_class = '''class LogOddsResidualWrapper:
    def __init__(self, base_estimator):
        self.base_estimator = base_estimator
        self.classes_ = getattr(base_estimator, 'classes_', [0, 1, 2])

    def _get_base_margin(self, X):
        import numpy as np
        X_arr = np.asarray(X)
        from src.models.feature_registry import CANONICAL_FEATURES_68
        try:
            idx_loh = CANONICAL_FEATURES_68.index("log_odds_home")
            idx_lod = CANONICAL_FEATURES_68.index("log_odds_draw")
            idx_loa = CANONICAL_FEATURES_68.index("log_odds_away")
            log_odds = X_arr[:, [idx_loh, idx_lod, idx_loa]]
            raw_odds = np.exp(log_odds)
            from src.models.evaluation.market_baseline import shin_devig
            base_margins = []
            for odds in raw_odds:
                try:
                    p = shin_devig(tuple(odds)).fair_probs
                except:
                    p = (0.333, 0.333, 0.334)
                # Clip to prevent log(0) and ensure valid simplex limits
                p = np.clip(p, 1e-6, 1.0 - 1e-6)
                p = p / np.sum(p)
                base_margins.append(np.log(p))
            return np.array(base_margins)
        except ValueError:
            # If log odds features are missing, return 0 margins
            return np.zeros((X.shape[0], 3))

    def fit(self, X, y, **kwargs):
        base_margin = self._get_base_margin(X)
        
        # XGBoost
        if hasattr(self.base_estimator, 'fit') and 'xgboost' in type(self.base_estimator).__module__:
            self.base_estimator.fit(X, y, base_margin=base_margin, **kwargs)
        # LightGBM
        elif hasattr(self.base_estimator, 'fit') and 'lightgbm' in type(self.base_estimator).__module__:
            self.base_estimator.fit(X, y, init_score=base_margin, **kwargs)
        # LogisticRegression / others not supporting base_margin natively
        else:
            self.base_estimator.fit(X, y, **kwargs)
            
        self.classes_ = getattr(self.base_estimator, 'classes_', [0, 1, 2])
        return self

    def predict_proba(self, X):
        import numpy as np
        from scipy.special import softmax
        base_margin = self._get_base_margin(X)
        
        # XGBoost
        if hasattr(self.base_estimator, 'predict_proba') and 'xgboost' in type(self.base_estimator).__module__:
            return self.base_estimator.predict_proba(X, base_margin=base_margin)
            
        # LightGBM
        elif hasattr(self.base_estimator, 'predict') and 'lightgbm' in type(self.base_estimator).__module__:
            # LightGBM predict_proba does not accept init_score/base_margin.
            # We must get raw scores, add base margin, and softmax.
            raw_preds = self.base_estimator.predict(X, raw_score=True)
            return softmax(raw_preds + base_margin, axis=1)
            
        # Fallback
        else:
            return self.base_estimator.predict_proba(X)
'''

code = re.sub(r'class LogOddsResidualWrapper:.*', new_class, code, flags=re.DOTALL)

with open('backend/src/models/ensemble.py', 'w', encoding='utf-8') as f:
    f.write(code)
