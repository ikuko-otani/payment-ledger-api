import logging

import structlog


def configure_structlog() -> None:
    structlog.configure(
        processors=[
            # TODO: implement (hint: add processors in this order:
            #   structlog.processors.TimeStamper(fmt="iso"),
            #   structlog.stdlib.add_log_level,
            #   structlog.processors.JSONRenderer())
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
