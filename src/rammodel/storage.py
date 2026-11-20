"""Create or migrate a local SQLite RAM case."""
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
import sqlite3


_APPLICATION_ID = 0x52414D43
_MIGRATIONS = ("001_initial.sql", "002_studies.sql", "003_provenance.sql")
SCHEMA_VERSION = len(_MIGRATIONS)


class InvalidCaseError(ValueError):
    """The database is not a supported RAM case."""


def _migrate(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if version > len(_MIGRATIONS):
            raise InvalidCaseError(f"RAM case schema {version} is newer than this program (supports {len(_MIGRATIONS)}). "
                                   "Open it with a newer RAM Model release; the file was not modified.")
        if application_id == 0 and version == 0:
            existing = connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
            if existing:
                raise InvalidCaseError("The file contains an unrecognised SQLite schema.")
            connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        elif application_id != _APPLICATION_ID or version == 0:
            raise InvalidCaseError("The file does not identify a supported RAM case.")
        for number in range(version + 1, len(_MIGRATIONS) + 1):
            sql = files("rammodel").joinpath(_MIGRATIONS[number - 1]).read_text(encoding="utf-8")
            statement = ""
            for line in sql.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise InvalidCaseError(f"Migration {number} ends with incomplete SQL.")
            connection.execute(f"PRAGMA user_version = {number}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


@contextmanager
def open_case(path: Path):
    """Open a case, commit successful work and release the file handle."""
    if path.suffix.lower() != ".ramcase":
        raise InvalidCaseError("Use a .ramcase file.")
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _migrate(connection)
        with connection:
            yield connection
    finally:
        connection.close()
