"""Compatibility path for the rejection-section helper tests removed by #998.

The behavioral coverage now lives in the eleven production-path consumer
modules.  Keeping this import-only module avoids presenting a deleted path to
repository-wide changed-file scanners while adding no test or database setup.
"""

from tests.section_rejection_helpers import game, rejection_rows


__all__ = ["game", "rejection_rows"]
