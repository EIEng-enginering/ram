from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rammodel import storage


class CaseStorageTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="RAM & Case ")
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "test case.ramcase"

    def test_create_and_reopen_with_literal_path(self):
        with storage.open_case(self.path) as db:
            # 0.3: literal 2 replaced by the current schema version (migration 003 added).
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (storage.SCHEMA_VERSION,))
            db.execute("INSERT INTO subsystem VALUES ('system', NULL, 'Production')")
        with storage.open_case(self.path) as db:
            self.assertEqual(db.execute("SELECT id FROM subsystem").fetchone(), ("system",))

    def test_foreign_database_is_preserved(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("CREATE TABLE other (id INTEGER)")
        finally:
            db.close()
        with self.assertRaises(storage.InvalidCaseError):
            with storage.open_case(self.path):
                self.fail("Unrecognised database was accepted")
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute("PRAGMA application_id").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema").fetchone(), ("other",))
        finally:
            db.close()

    def test_migration_rolls_back_as_a_unit(self):
        with patch.object(storage, "_MIGRATIONS", ("001_initial.sql", "missing.sql")):
            with self.assertRaises(FileNotFoundError):
                with storage.open_case(self.path):
                    self.fail("Incomplete migrations were accepted")
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))
            self.assertEqual(db.execute("PRAGMA application_id").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema").fetchall(), [])
        finally:
            db.close()

    def test_future_schema_rejected(self):
        with storage.open_case(self.path) as db:
            # 0.3: literal 3 was "one newer than 0.2"; keep that intent.
            db.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 1}")
        with self.assertRaises(storage.InvalidCaseError):
            with storage.open_case(self.path):
                self.fail("Future schema was accepted")

    def test_zero_distinct_from_missing_and_source_required(self):
        with storage.open_case(self.path) as db:
            db.execute("INSERT INTO subsystem VALUES ('system', NULL, 'Production')")
            db.execute("INSERT INTO equipment VALUES ('pump', 'system', 'P-001', 'Pump')")
            db.execute("INSERT INTO failure_mode VALUES ('mode', 'pump', 'Trip', 'revealed', 'exponential', 'operating')")
            db.execute("INSERT INTO source (id, kind, citation) VALUES ('demo', 'example', 'EXAMPLE')")
            value = ("mode", "logistics_hours", 0.0, "demo", "synthetic fixture", "0", "h", "unreviewed", "unassessed", None, None, None)
            db.execute("INSERT INTO mode_value VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", value)
            self.assertEqual(db.execute("SELECT value FROM mode_value WHERE field = 'logistics_hours'").fetchone(), (0.0,))
            self.assertIsNone(db.execute("SELECT value FROM mode_value WHERE field = 'active_repair_hours'").fetchone())
            untraceable = ("mode", "active_repair_hours", 1.0, "unknown") + value[4:]
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO mode_value VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", untraceable)
