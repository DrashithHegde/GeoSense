"""Google Earth Engine helper package for GeoSense.

This package provides a small wrapper to initialize Earth Engine using
service-account or ADC (Application Default Credentials). It avoids
interactive auth for CI/deployments and never stores secrets in the repo.
"""

from .gee_client import initialize_ee, is_initialized

__all__ = ["initialize_ee", "is_initialized"]
