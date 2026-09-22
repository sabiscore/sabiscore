import re

with open('backend/scripts/evaluate_split_conformal.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = r"""    conformal = SplitConformalClassifier\(
        estimator=model,
        confidence_level=CONFIDENCE_LEVELS,
        conformity_score="lac",  # non-adaptive; §21 prohibits aps/raps here
        prefit=True,
    \)
    conformal\.conformalize\(X_cal, y_cal\)
    _, y_sets = conformal\.predict_set\(X_test\).*?return \{.*?\}"""

replacement = """    methods = ["lac", "aps", "raps"]
    method_results = {}
    
    proba = model.predict_proba(X_test)
    point_pred = proba.argmax(axis=1)
    
    for method in methods:
        conformal = SplitConformalClassifier(
            estimator=model,
            confidence_level=CONFIDENCE_LEVELS,
            conformity_score=method,
            prefit=True,
        )
        conformal.conformalize(X_cal, y_cal)
        _, y_sets = conformal.predict_set(X_test)

        per_level: dict[str, Any] = {}
        for i, level in enumerate(CONFIDENCE_LEVELS):
            sets = y_sets[:, :, i]
            covered = sets[np.arange(len(y_test)), y_test]
            sizes = sets.sum(axis=1)
            empirical = float(covered.mean())

            missed = ~covered.astype(bool)
            by_class = {
                CLASS_NAMES[c]: {
                    "n": int((y_test == c).sum()),
                    "missed": int((missed & (y_test == c)).sum()),
                    "miss_rate": float(
                        (missed & (y_test == c)).sum() / max((y_test == c).sum(), 1)
                    ),
                }
                for c in range(3)
            }

            per_level[f"{level:.2f}"] = {
                "nominal_coverage": level,
                "empirical_coverage": empirical,
                "coverage_gap": empirical - level,
                "mean_set_size": float(sizes.mean()),
                "set_size_distribution": {
                    str(k): int((sizes == k).sum()) for k in range(0, 4)
                },
                "singleton_rate": float((sizes == 1).mean()),
                "full_set_rate": float((sizes == 3).mean()),
                "empty_set_rate": float((sizes == 0).mean()),
                "failure_concentration_by_true_class": by_class,
            }

        stability: dict[str, Any] = {}
        mid = len(y_test) // 2
        for label, sl in (("test_first_half", slice(0, mid)), ("test_second_half", slice(mid, None))):
            window: dict[str, Any] = {}
            for i, level in enumerate(CONFIDENCE_LEVELS):
                sets = y_sets[sl, :, i]
                yy = y_test[sl]
                window[f"{level:.2f}"] = float(sets[np.arange(len(yy)), yy].mean())
            stability[label] = {"n": int(len(y_test[sl])), "empirical_coverage": window}
            
        method_results[method] = {
            "levels": per_level,
            "temporal_stability": stability,
        }

    return {
        "league": league,
        "n_conformalize": int(len(y_cal)),
        "n_test": int(len(y_test)),
        "conformalize_date_range": [str(sorted_dates[0]), str(sorted_dates[split - 1])],
        "test_date_range": [str(sorted_dates[split]), str(sorted_dates[-1])],
        "point_accuracy_on_test": float((point_pred == y_test).mean()),
        "artifact_reported_accuracy": model.metadata.get("accuracy"),
        "methods": method_results,
    }"""

code = re.sub(target, replacement, code, flags=re.DOTALL)

with open('backend/scripts/evaluate_split_conformal.py', 'w', encoding='utf-8') as f:
    f.write(code)
