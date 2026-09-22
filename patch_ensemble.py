import re

with open('backend/src/models/ensemble.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = r"""class LogOddsResidualWrapper:
    def __init__\(self, base_estimator\):
        self\.base_estimator = base_estimator
        self\.classes_ = getattr\(base_estimator, 'classes_', \[0, 1, 2\]\)"""

replacement = """from sklearn.base import BaseEstimator

class LogOddsResidualWrapper(BaseEstimator):
    def __init__(self, base_estimator):
        self.base_estimator = base_estimator
        self.classes_ = getattr(base_estimator, 'classes_', [0, 1, 2])"""

code = re.sub(target, replacement, code, flags=re.DOTALL)

with open('backend/src/models/ensemble.py', 'w', encoding='utf-8') as f:
    f.write(code)
