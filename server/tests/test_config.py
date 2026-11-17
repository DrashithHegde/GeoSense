"""Configuration tests that never expose credential values."""
from __future__ import annotations

import unittest
from unittest import mock


class ConfigTests(unittest.TestCase):
    def test_gee_project_is_a_supported_setting(self) -> None:
        from app.core.config import Settings
        self.assertEqual(Settings(gee_project="example-project").gee_project, "example-project")

    def test_hosted_database_url_wins_and_is_normalised(self) -> None:
        from app import database
        with mock.patch.object(database.settings, "database_url_override", "postgres://u:p@db.example:5432/geo"), \
             mock.patch.object(database.settings, "db_sslmode", "require"):
            url = database.database_url()
        self.assertEqual(url.drivername, "postgresql+psycopg2")
        self.assertEqual(url.host, "db.example")
        self.assertEqual(url.query.get("sslmode"), "require")

    def test_cors_origins_are_trimmed(self) -> None:
        from app.core.config import Settings
        s = Settings(cors_origins=" https://a.vercel.app/ ,https://b.example ")
        self.assertEqual(s.parsed_cors_origins, ["https://a.vercel.app", "https://b.example"])
