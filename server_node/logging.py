"""
Centralized logging configuration for server_node.

Provides structured logging with:
- Console output with colors
- Optional file logging
- Level filtering
- Memory buffer for Web UI
"""
import logging
import sys
from datetime import datetime
from collections import deque

# Memory buffer for the Web UI (holds last 100 logs)
log_buffer = deque(maxlen=100)

class ColoredFormatter(logging.Formatter):
    """Formatter with colored output for console."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Keep original levelname for other handlers
        orig_levelname = record.levelname
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        msg = super().format(record)
        # Restore for safety (though record is usually transient)
        record.levelname = orig_levelname
        return msg

class MemoryHandler(logging.Handler):
    """
    Stores log records in a deque for the Web UI.
    Filters out 'developer' noise (PROFILE, DEBUG) to keep it 'Tactical'.
    """
    def emit(self, record):
        try:
            msg = self.format(record)
            # TACTICAL FILTERING
            # 1. Skip PROFILE logs (latency metrics)
            if "[PROFILE]" in msg or "drain took" in msg:
                return
            # 2. Skip DEBUG logs
            if record.levelname == "DEBUG":
                return
            # 3. Skip UI internal logs
            if record.name == "web_ui" and "Updating" in msg:
                return
                
            log_buffer.append(msg)
        except Exception:
            self.handleError(record)

def setup_logging(level: str = "INFO", log_file: str = None):
    """
    Configure logging for the server.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # 1. Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    ))
    root_logger.addHandler(console_handler)
    
    # 2. Memory Handler for Web UI (Clean format)
    memory_handler = MemoryHandler()
    memory_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    ))
    root_logger.addHandler(memory_handler)
    
    # 3. Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        ))
        root_logger.addHandler(file_handler)
    
    # Suppress noisy libraries
    logging.getLogger("aioice").setLevel(logging.WARNING)
    logging.getLogger("aiortc").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    logging.info("Logging initialized at %s level", level)


# Module-level logger for easy import
logger = logging.getLogger("server_node")
