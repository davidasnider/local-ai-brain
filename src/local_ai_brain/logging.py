import logging
import os
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        try:
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
        except ValueError:
            # Call stack is too shallow
            depth = 0

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(testing: bool = False):
    logger.remove()
    if not testing:
        log_path = os.path.expanduser(
            os.getenv("LOCAL_AI_BRAIN_LOG_PATH", "~/Library/Logs/local-ai-brain.log")
        )
        log_directory = os.path.dirname(log_path)
        if log_directory:
            os.makedirs(log_directory, exist_ok=True)
        logger.add(
            log_path,
            rotation="10 MB",
            retention="1 week",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )

    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # Intercept standard library logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for _log in ["uvicorn", "uvicorn.error", "fastapi"]:
        _logger = logging.getLogger(_log)
        _logger.handlers = [InterceptHandler()]
        _logger.propagate = False
