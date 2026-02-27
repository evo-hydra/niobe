"""Idempotent stderr logging setup."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure Niobe logging to stderr. Safe to call multiple times."""
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    logger = logging.getLogger("niobe")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    _CONFIGURED = True
