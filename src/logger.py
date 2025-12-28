import logging
import sys

def setup_logger(name: str) -> logging.Logger:
    """
    Configure and return a logger with a standard format.
    Adheres to KISS principle: Simple console output, standard format.
    """
    logger = logging.getLogger(name)
    
    # Only add handler if it doesn't have one (prevent duplicate logs)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Use stdout to ensure it's captured by Streamlit or CLI
        handler = logging.StreamHandler(sys.stdout)
        
        # Format: [Timestamp] [LoggerName] Message
        # Matches the previous style: [2025-12-28 14:00:00] [Matcher] ...
        formatter = logging.Formatter(
            '[%(asctime)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger
