import sys
sys.path.insert(0, '.')

print("Testing core imports...")

try:
    import app.main
    print("✓ app.main")
except Exception as e:
    print(f"✗ app.main: {e}")
    sys.exit(1)

try:
    import app.api.routes
    print("✓ app.api.routes")
except Exception as e:
    print(f"✗ app.api.routes: {e}")
    sys.exit(1)

try:
    import app.services.surfaces.aqi_surface
    print("✓ app.services.surfaces.aqi_surface")
except Exception as e:
    print(f"✗ app.services.surfaces.aqi_surface: {e}")
    sys.exit(1)

try:
    import app.services.surfaces.ndvi_surface
    print("✓ app.services.surfaces.ndvi_surface")
except Exception as e:
    print(f"✗ app.services.surfaces.ndvi_surface: {e}")
    sys.exit(1)

print("\nAll imports successful!")
