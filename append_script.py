
with open('backend/src/models/ensemble.py', 'a') as f:
    f.write('''

class LogOddsResidualWrapper:
    def __init__(self, base_estimator):
        self.base_estimator = base_estimator
        self.classes_ = getattr(base_estimator, 'classes_', [0, 1, 2])

    def _get_base_margin(self, X):
        import numpy as np
        X_arr = np.asarray(X)
        from src.models.feature_registry import CANONICAL_FEATURES_68
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
            base_margins.append(np.log(p))
        return np.array(base_margins)

    def fit(self, X, y, **kwargs):
        base_margin = self._get_base_margin(X)
        if hasattr(self.base_estimator, 'fit') and 'xgboost' in type(self.base_estimator).__module__:
            self.base_estimator.fit(X, y, base_margin=base_margin, **kwargs)
        else:
            self.base_estimator.fit(X, y, **kwargs)
        self.classes_ = getattr(self.base_estimator, 'classes_', [0, 1, 2])
        return self

    def predict_proba(self, X):
        base_margin = self._get_base_margin(X)
        if hasattr(self.base_estimator, 'predict_proba') and 'xgboost' in type(self.base_estimator).__module__:
            return self.base_estimator.predict_proba(X, base_margin=base_margin)
        else:
            return self.base_estimator.predict_proba(X)
''')
