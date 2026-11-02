"""Configuration tests that never expose credential values."""
from __future__ import annotations

import unittest

from app.core.config import Settings


class ConfigTests(unittest.TestCase):
    def test_aqicn_token_is_a_supported_setting(self) -> None:
        self.assertEqual(Settings(aqicn_token="test-token").aqicn_token, "test-token")

    def test_gee_project_is_a_supported_setting(self) -> None:
        self.assertEqual(Settings(gee_project="example-project").gee_project, "example-project")
