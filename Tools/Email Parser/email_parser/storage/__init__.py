"""Storage backends for parsed documents and artifacts."""

from email_parser.storage.paths import StoragePaths
from email_parser.storage.sqlite_index import SqliteIndex
from email_parser.storage.writer import Store

__all__ = ["SqliteIndex", "StoragePaths", "Store"]
