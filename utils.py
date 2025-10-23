import logging, os
from logging.handlers import RotatingFileHandler

def setup_logger():
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        fh = RotatingFileHandler("logs/app.log", maxBytes=2_000_000, backupCount=3)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
