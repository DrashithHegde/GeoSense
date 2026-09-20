"""Minimal Google Earth Engine client for server-side initialization.

Behavior:
- Prefer service-account ADC via `GOOGLE_APPLICATION_CREDENTIALS`.
- If not present, attempt to initialize using default credentials (user
  credentials saved by `earthengine authenticate`) and surface helpful
  error messages.

This module does NOT perform any heavy computation or data downloads — the
test script uses a small metadata query only.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

import ee
from google.oauth2 import service_account

from app.core.config import get_settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def is_initialized() -> bool:
    try:
        # ee.data.getvalue will raise if not initialized
        ee.data.getInfo()
        return True
    except Exception:
        return False


def initialize_ee(project: Optional[str] = None) -> None:
    """Initialize Earth Engine for server use.

    Initialization order:
    1. If `GOOGLE_APPLICATION_CREDENTIALS` is set, use it to create
       service account credentials and call `ee.Initialize(credentials, project)`.
    2. Try `ee.Initialize()` with default credentials (ADC / interactive auth).

    Raises an exception with a helpful message if initialization fails.
    """
    project = project or get_settings().gee_project

    # Already initialized
    if is_initialized():
        logger.info("Earth Engine is already initialized.")
        return

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path:
        if not os.path.exists(creds_path):
            raise FileNotFoundError(
                f"GOOGLE_APPLICATION_CREDENTIALS is set to {creds_path} but the file does not exist"
            )

        logger.info("Initializing Earth Engine using service account key: %s", creds_path)
        # Build google credentials with Earth Engine scopes
        scopes = [
            "https://www.googleapis.com/auth/earthengine",
            "https://www.googleapis.com/auth/cloud-platform",
        ]
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        # Initialize EE
        try:
            ee.Initialize(credentials=creds, project=project)
            logger.info("Earth Engine initialized with service account credentials.")
            return
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Earth Engine with service account: {e}")

    # Fallback: try default ee.Initialize() (may require prior `earthengine authenticate`)
    logger.info("Attempting Earth Engine initialization using default credentials (ADC/user auth).")
    try:
        ee.Initialize(project=project)
        logger.info("Earth Engine initialized with default credentials.")
        return
    except Exception as e:
        raise RuntimeError(
            "Earth Engine initialization failed. To use service account auth set the environment variable "
            "`GOOGLE_APPLICATION_CREDENTIALS` to a service account JSON file with access to Earth Engine, "
            "or run `earthengine authenticate` locally and ensure credentials are available. "
            f"Original error: {e}"
        )
