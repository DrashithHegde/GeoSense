"""Test that import paths don't have 'from server.' issues"""
import sys
sys.path.insert(0, '.')

print("Testing import path fix (no server. prefix)...")
print()

# Test 1: Direct module imports that were changed
tests_passed = 0
tests_failed = 0

try:
    from openaq.derive_aqi_grid import idw_estimate
    print("✓ openaq.derive_aqi_grid")
    tests_passed += 1
except ModuleNotFoundError as e:
    if "'server'" in str(e):
        print(f"✗ openaq.derive_aqi_grid - IMPORT PATH BUG: {e}")
        tests_failed += 1
    else:
        print(f"✗ openaq.derive_aqi_grid - Different issue: {e}")
        tests_failed += 1

try:
    from gee.ingest_lst import COMPOSITE_WINDOW_DAYS
    print("✓ gee.ingest_lst")
    tests_passed += 1
except ModuleNotFoundError as e:
    if "'server'" in str(e):
        print(f"✗ gee.ingest_lst - IMPORT PATH BUG: {e}")
        tests_failed += 1
    else:
        print(f"✗ gee.ingest_lst - Different issue: {e}")
        tests_failed += 1

try:
    from aqicn.ingest_aqicn import parse_aqicn_time
    print("✓ aqicn.ingest_aqicn")
    tests_passed += 1
except ModuleNotFoundError as e:
    if "'server'" in str(e):
        print(f"✗ aqicn.ingest_aqicn - IMPORT PATH BUG: {e}")
        tests_failed += 1
    else:
        print(f"✗ aqicn.ingest_aqicn - Different issue: {e}")
        tests_failed += 1

try:
    from scripts.scheduler import should_run_feature_pipeline
    print("✓ scripts.scheduler")
    tests_passed += 1
except ModuleNotFoundError as e:
    if "'server'" in str(e):
        print(f"✗ scripts.scheduler - IMPORT PATH BUG: {e}")
        tests_failed += 1
    else:
        print(f"✗ scripts.scheduler - Different issue: {e}")
        tests_failed += 1

print()
print(f"Results: {tests_passed} passed, {tests_failed} failed")
print()

if "'server'" in str(sys.modules):
    print("ISSUE: 'server' found in sys.modules - suggests import path bug remains")
else:
    print("✓ No 'server' module in sys.modules - import path fix working")

sys.exit(0 if tests_failed == 0 else 1)
