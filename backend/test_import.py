import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from src.data.aggregator import get_match_features
    assert callable(get_match_features)
    print("Import successful!")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Other error: {e}")
