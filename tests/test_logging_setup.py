"""Tests for logging setup."""

import logging

import niobe.logging_setup as ls


class TestSetupLogging:
    def setup_method(self):
        # Reset the module-level flag for each test
        ls._CONFIGURED = False
        logger = logging.getLogger("niobe")
        logger.handlers.clear()

    def test_setup_creates_handler(self):
        ls.setup_logging()
        logger = logging.getLogger("niobe")
        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO

    def test_idempotent(self):
        ls.setup_logging()
        ls.setup_logging()
        logger = logging.getLogger("niobe")
        assert len(logger.handlers) == 1

    def test_custom_level(self):
        ls.setup_logging(level=logging.DEBUG)
        logger = logging.getLogger("niobe")
        assert logger.level == logging.DEBUG
