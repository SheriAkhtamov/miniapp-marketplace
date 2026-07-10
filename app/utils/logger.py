import sys
from loguru import logger
from app.config import settings

# Configure logger
logger.remove() # Remove default handler
logger.add(sys.stdout, level="INFO")
logger.add("logs/app.log", rotation="50 MB", retention="14 days", level="INFO", compression="zip")

__all__ = ["logger"]
