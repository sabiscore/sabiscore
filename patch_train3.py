import re

with open('backend/scripts/train_on_real_matches.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = r"""def _instantiate\(learner: str, params: Dict\[str, object\], \*, n_jobs: int = -1\):
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier

    if learner == "random_forest":
        return RandomForestClassifier\(random_state=_TRAINING_SEED, n_jobs=n_jobs, \*\*params\)
    if learner == "xgboost":
        return XGBClassifier\(
            objective="multi:softprob", num_class=3, random_state=_TRAINING_SEED,
            tree_method="hist", eval_metric="mlogloss", n_jobs=n_jobs, \*\*params,
        \)
    return LGBMClassifier\(
        objective="multiclass", num_class=3, random_state=_TRAINING_SEED, verbose=-1,
        n_jobs=n_jobs, \*\*params,
    \)"""

replacement = """def _instantiate(learner: str, params: Dict[str, object], *, n_jobs: int = -1):
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier
    from src.models.ensemble import LogOddsResidualWrapper

    if learner == "random_forest":
        clf = RandomForestClassifier(random_state=_TRAINING_SEED, n_jobs=n_jobs, **params)
    elif learner == "xgboost":
        clf = XGBClassifier(
            objective="multi:softprob", num_class=3, random_state=_TRAINING_SEED,
            tree_method="hist", eval_metric="mlogloss", n_jobs=n_jobs, **params,
        )
    else:
        clf = LGBMClassifier(
            objective="multiclass", num_class=3, random_state=_TRAINING_SEED, verbose=-1,
            n_jobs=n_jobs, **params,
        )
    return LogOddsResidualWrapper(clf)"""

code = re.sub(target, replacement, code, flags=re.DOTALL)

with open('backend/scripts/train_on_real_matches.py', 'w', encoding='utf-8') as f:
    f.write(code)
