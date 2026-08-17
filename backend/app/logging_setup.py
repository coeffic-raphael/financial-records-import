"""Make the application's own log lines visible.

Under uvicorn the root logger keeps its default WARNING level and no handler,
so every `logger.info(...)` in this codebase was dropped: the provider chosen at
startup, and the line written after EVERY extraction carrying provider, model,
record count and duration. Errors still surfaced -- they clear WARNING -- which
is why the silence went unnoticed.

The handler is attached to the `app` namespace rather than to the root logger:
uvicorn owns its own configuration, and reconfiguring the root would either
fight it or duplicate its output.
"""

import logging

APP_LOGGER = "app"


def configure_logging(level: str) -> None:
    """Idempotent: `--reload` and the test suite may call this repeatedly."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))

    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(level.upper())
    # `logging.config.fileConfig` defaults to disable_existing_loggers=True, and
    # alembic/env.py calls it. Whenever migrations run in the SAME process --
    # the test suite does -- every logger built before that call is switched
    # off. Configuring the level without clearing this flag would look correct
    # and still print nothing.
    #
    # The flag is per logger and `isEnabledFor` reads it on the one doing the
    # logging, so clearing the parent alone changes nothing: every child that
    # already exists must be cleared too.
    logger.disabled = False
    prefix = APP_LOGGER + "."
    for name, existing in logging.root.manager.loggerDict.items():
        if name.startswith(prefix) and isinstance(existing, logging.Logger):
            existing.disabled = False
    # Assigned, not appended: calling this twice must not double every line.
    logger.handlers = [handler]
    # uvicorn's handlers live on its own loggers; propagating would print
    # nothing extra here, but would let a future root config duplicate lines.
    logger.propagate = False
