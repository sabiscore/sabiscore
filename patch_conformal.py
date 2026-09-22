import re

with open('backend/scripts/evaluate_split_conformal.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace restriction mentions
code = re.sub(r'# non-adaptive; §21 prohibits aps/raps here', '# replaced with loop over [lac, aps, raps]', code)
code = re.sub(r'conformity_score="lac",', 'conformity_score=score_method,', code)

# We need to loop over scoring methods.
# Wait, the best way is to write a regex that wraps the conformal = SplitConformalClassifier block in a loop over score_methods.
