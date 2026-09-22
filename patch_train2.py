with open('backend/scripts/train_on_real_matches.py', 'r', encoding='utf-8') as f:
    code = f.read()

start_str = "        method = select_calibration_method(n)"
end_str = "    except Exception as exc:"

start_idx = code.find(start_str)
end_idx = code.find(end_str, start_idx)

replacement = """        from src.models.calibration import compare_calibration_methods
        fitted_cal = compare_calibration_methods(
            league,
            y_calibration.astype(np.int64), proba_cal,
            y_holdout.astype(np.int64), proba_hold,
        )
        return fitted_cal
"""

new_code = code[:start_idx] + replacement + code[end_idx:]

with open('backend/scripts/train_on_real_matches.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
