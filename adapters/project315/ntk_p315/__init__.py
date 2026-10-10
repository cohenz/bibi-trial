"""Project 315 adapter: maps an export (JSON/CSV/canonical snapshot) to
Project315Event records with full provenance. See docs/project315-adapter.md."""

from .importer import ImportFailed, import_export, to_event
from .mapping import CANONICAL_FIELDS, PARSER_VERSION

__all__ = ["ImportFailed", "import_export", "to_event", "CANONICAL_FIELDS", "PARSER_VERSION"]
