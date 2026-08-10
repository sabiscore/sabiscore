import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    from backend.src.services.data_processing import DataProcessingService
    assert callable(DataProcessingService)
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Error: {e}")
