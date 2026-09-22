import re

with open('backend/scripts/train_on_real_matches.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = r"        method = select_calibration_method\(n\).*?return FittedCalibrator\([^)]+\)"

replacement = """        from src.models.calibration import compare_calibration_methods
        fitted_cal = compare_calibration_methods(
            league,
            y_calibration.astype(np.int64), proba_cal,
            y_holdout.astype(np.int64), proba_hold,
        )
        return fitted_cal"""

code = re.sub(r'        method = select_calibration_method\(n\).*?return FittedCalibrator\([^)]+\)', replacement, code, flags=re.DOTALL)

with open('backend/scripts/train_on_real_matches.py', 'w', encoding='utf-8') as f:
    f.write(code)
