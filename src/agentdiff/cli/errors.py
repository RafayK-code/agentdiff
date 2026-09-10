from __future__ import annotations


class CliError(Exception):
    """User-facing CLI error; message only.

    ``main()`` prints it to stderr and exits 1 (R9). Raised for CLI-level
    domain errors (bad selector, unknown change/branch/format, bad --root).
    """
