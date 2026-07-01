import sys
import os
from loguru import logger


class Logger:
    @staticmethod
    def create(env: str):
        logger.remove()
        logger.add(
            sys.stderr,
            level="DEBUG" if env == "dev" else "INFO",
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        )
        return logger


logger = Logger.create(os.getenv("ENVIRONMENT", "dev"))
