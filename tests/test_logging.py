from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from funhou_hook.logging import LogKind, get_logger, initialize_logging


@pytest.fixture
def logging_dir() -> Iterator[Path]:
    path = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_logging(logging_dir: Path) -> Path:
    initialize_logging(logging_dir / "operational.log")
    yield logging_dir
    for kind in LogKind:
        logger = get_logger(kind)
        handlers = list(logger.handlers)
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()


def test_get_logger_supports_all_log_kinds() -> None:
    for kind in LogKind:
        logger = get_logger(kind)

        assert isinstance(logger, logging.Logger)
        assert logger.propagate is False


def test_initialize_logging_writes_operational_log_with_extra_fields(logging_dir: Path) -> None:
    log_path = logging_dir / "logs" / "operational.log"

    initialize_logging(log_path)
    logger = get_logger(LogKind.Operational)
    logger.info("Slack delivery failed", extra={"channel": "#general", "retry_count": 2})

    contents = log_path.read_text(encoding="utf-8")
    assert "[INFO] Slack delivery failed" in contents
    assert "channel='#general'" in contents
    assert "retry_count=2" in contents


def test_get_logger_and_initialize_logging_do_not_duplicate_operational_handlers(
    logging_dir: Path,
) -> None:
    log_path = logging_dir / "operational.log"

    initialize_logging(log_path)
    logger = get_logger(LogKind.Operational)
    initial_count = len(logger.handlers)

    same_logger = get_logger(LogKind.Operational)
    initialize_logging(log_path)

    assert same_logger is logger
    assert len(logger.handlers) == initial_count == 1


def test_initialize_logging_retargets_operational_handler_without_duplicates(
    logging_dir: Path,
) -> None:
    first_path = logging_dir / "first.log"
    second_path = logging_dir / "second.log"

    initialize_logging(first_path)
    logger = get_logger(LogKind.Operational)
    logger.info("first message")

    initialize_logging(second_path)
    logger.info("second message")

    assert first_path.read_text(encoding="utf-8").count("message") == 1
    assert "first message" in first_path.read_text(encoding="utf-8")
    assert "second message" not in first_path.read_text(encoding="utf-8")
    assert "second message" in second_path.read_text(encoding="utf-8")
    assert len(logger.handlers) == 1


def test_non_operational_loggers_keep_a_single_null_handler() -> None:
    for kind in (LogKind.Notification, LogKind.Debug, LogKind.StateAudit):
        logger = get_logger(kind)
        first_count = len(logger.handlers)

        get_logger(kind)
        initialize_logging()

        assert len(logger.handlers) == first_count == 1
