from __future__ import annotations

import logging

# The single logger namespace every diskdoctor module logs under. Module
# loggers created via `logging.getLogger(__name__)` all sit beneath this, so
# configuring this one handler/level governs the whole package.
_ROOT_LOGGER_NAME = "diskdoctor"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Marker set on the handler we install, so a second configure_logging call can
# recognise our own handler and avoid attaching a duplicate (which would print
# every line twice). Distinguishes our handler from ones an embedding app added.
_HANDLER_MARKER = "_diskdoctor_handler"


def _already_configured(logger: logging.Logger) -> bool:
    return any(getattr(h, _HANDLER_MARKER, False) for h in logger.handlers)


def configure_logging(verbose: bool) -> None:
    """Attach a stderr handler to the ``diskdoctor`` logger.

    INFO by default, DEBUG when ``verbose``. Idempotent: our handler is added at
    most once per process, but the level is refreshed on every call so a later
    ``--verbose`` invocation can still raise verbosity. We deliberately do not
    touch the root logger or uvicorn's config — uvicorn installs its own
    handlers, and our logger propagates independently.
    """
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    if _already_configured(logger) or logger.handlers:
        # Already wired up (by us or by an embedding app). Don't double-add a
        # handler — that would duplicate every line — but the level bump above
        # still takes effect.
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)
    logger.addHandler(handler)
    # Keep our records off the root logger so we don't double-print when an
    # embedding process (or uvicorn) has also configured the root handler.
    logger.propagate = False
