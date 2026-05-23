"""
=============================================================================
Logging Configuration - Project Spotless
=============================================================================
Centralized logging setup for the Spotless system.

Features:
- File and console logging
- Automatic log rotation (resets after 7 days)
- Session-specific log entries
- Log file path management

Log files are stored in:
    ~/.spotless/logs/spotless.log       - Main log file
    ~/.spotless/logs/session_YYYYMMDD.log - Daily session logs
=============================================================================
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Optional

# =============================================================================
# Log Configuration
# =============================================================================
LOG_DIR = Path.home() / ".spotless" / "logs"
MAIN_LOG_FILE = LOG_DIR / "spotless.log"
SESSION_LOG_FILE = LOG_DIR / "sessions.log"

# Log format
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FORMAT_DETAILED = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

# Default log level
DEFAULT_LOG_LEVEL = logging.INFO

# Max log file size (5 MB)
MAX_LOG_SIZE = 5 * 1024 * 1024

# Number of backup files to keep
BACKUP_COUNT = 5


# =============================================================================
# Log File Management
# =============================================================================
def ensure_log_directory() -> Path:
    """Ensure the log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def get_log_file_path(machine_id: str = "") -> Path:
    """
    Get the path to the main log file.
    
    Args:
        machine_id: Optional machine ID to include in filename
        
    Returns:
        Path to log file
    """
    ensure_log_directory()
    
    if machine_id:
        return LOG_DIR / f"spotless_{machine_id}.log"
    return MAIN_LOG_FILE


def get_session_log_file() -> Path:
    """Get the path to the session log file."""
    ensure_log_directory()
    return SESSION_LOG_FILE


def reset_log_file_if_old(file_path: Path, days: int = 7) -> bool:
    """
    Reset log file if it's older than specified days.
    
    Args:
        file_path: Path to the log file
        days: Number of days after which to reset
        
    Returns:
        True if file was reset, False otherwise
    """
    if not file_path.exists():
        return False
        
    try:
        file_creation_time = datetime.fromtimestamp(os.path.getctime(file_path))
        if (datetime.now() - file_creation_time).days >= days:
            # Clear existing handlers first
            for handler in logging.getLogger().handlers[:]:
                handler.close()
                logging.getLogger().removeHandler(handler)
            
            # Archive the old log file
            archive_name = file_path.with_suffix(
                f".{file_creation_time.strftime('%Y%m%d')}.log"
            )
            if archive_name.exists():
                archive_name.unlink()
            file_path.rename(archive_name)
            
            # Create a new empty log file
            file_path.touch()
            return True
            
    except Exception as e:
        print(f"Error resetting log file: {e}")
        
    return False


# =============================================================================
# Logger Setup
# =============================================================================
def setup_logging(
    machine_id: str = "",
    log_level: int = DEFAULT_LOG_LEVEL,
    console_level: int = logging.INFO,
    include_detailed_format: bool = False,
    enable_db_logging: bool = True
) -> logging.Logger:
    """
    Setup logging for the application.
    
    Args:
        machine_id: Machine ID for log file naming
        log_level: Logging level for file handler
        console_level: Logging level for console handler
        include_detailed_format: Use detailed format with file/line info
        enable_db_logging: Also send logs to the system_logs DB table
        
    Returns:
        Configured logger
    """
    global _db_log_handler

    # Ensure log directory exists
    ensure_log_directory()
    
    # Get log file path
    log_file = get_log_file_path(machine_id)
    
    # Check if log file should be reset
    reset_log_file_if_old(log_file, days=7)
    
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)
    
    # Select format
    log_format = LOG_FORMAT_DETAILED if include_detailed_format else LOG_FORMAT
    formatter = logging.Formatter(log_format)
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console_handler)

    # Database handler (logs → system_logs table)
    if enable_db_logging:
        try:
            from db_manager import DatabaseConfig
            from db_log_handler import DatabaseLogHandler

            db_config = DatabaseConfig.from_env()
            if db_config.host:
                _db_log_handler = DatabaseLogHandler(
                    db_config, machine_id=machine_id, level=logging.INFO
                )
                _db_log_handler.setFormatter(logging.Formatter(LOG_FORMAT))
                root_logger.addHandler(_db_log_handler)
        except Exception as e:
            print(f"[logging_config] DB log handler not available: {e}")
    
    # Log startup
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info(f"Logging initialized for machine: {machine_id or 'default'}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"DB logging: {'enabled' if enable_db_logging and _db_log_handler else 'disabled'}")
    logger.info("=" * 60)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(name)


# =============================================================================
# Session Logging
# =============================================================================
class SessionLogger:
    """
    Logger for individual bath sessions.
    
    Provides structured logging for session events:
    - Session start
    - Stage transitions
    - Session completion
    - Errors/warnings
    """
    
    def __init__(self, machine_id: str = ""):
        self.logger = logging.getLogger("session")
        self.machine_id = machine_id
        self._current_session = None
        self._session_start_time = None
        
    def start_session(self, session_type: str, qr_code: str):
        """Log session start."""
        self._current_session = {
            'type': session_type,
            'qr_code': qr_code,
            'start_time': datetime.now()
        }
        self._session_start_time = datetime.now()
        
        self.logger.info("=" * 60)
        self.logger.info(f"SESSION STARTED")
        self.logger.info(f"  Machine ID: {self.machine_id}")
        self.logger.info(f"  Session Type: {session_type}")
        self.logger.info(f"  QR Code: {qr_code}")
        self.logger.info(f"  Start Time: {self._session_start_time}")
        self.logger.info("=" * 60)
        
    def log_stage(self, stage_name: str, details: str = ""):
        """Log a stage transition."""
        timestamp = datetime.now()
        elapsed = ""
        
        if self._session_start_time:
            elapsed_seconds = (timestamp - self._session_start_time).total_seconds()
            elapsed = f" [+{elapsed_seconds:.0f}s]"
            
        self.logger.info(f"STAGE: {stage_name}{elapsed}")
        if details:
            self.logger.info(f"  {details}")
            
    def log_params(self, **params):
        """Log session parameters."""
        self.logger.info("Session Parameters:")
        for key, value in params.items():
            self.logger.info(f"  {key}: {value}")
            
    def log_device_action(self, device_name: str, action: str):
        """Log a device action."""
        self.logger.debug(f"DEVICE: {device_name} -> {action}")
        
    def log_warning(self, message: str):
        """Log a warning."""
        self.logger.warning(f"WARNING: {message}")
        
    def log_error(self, message: str):
        """Log an error."""
        self.logger.error(f"ERROR: {message}")
        
    def end_session(self, status: str = "completed"):
        """Log session end."""
        end_time = datetime.now()
        
        if self._session_start_time:
            duration = (end_time - self._session_start_time).total_seconds()
            duration_str = f"{int(duration // 60)}m {int(duration % 60)}s"
        else:
            duration = 0
            duration_str = "N/A"
            
        self.logger.info("=" * 60)
        self.logger.info(f"SESSION ENDED")
        self.logger.info(f"  Status: {status.upper()}")
        self.logger.info(f"  End Time: {end_time}")
        self.logger.info(f"  Duration: {duration_str}")
        self.logger.info("=" * 60)
        
        self._current_session = None
        self._session_start_time = None
        
        return int(duration)


# =============================================================================
# Global DB Log Handler (set by setup_logging)
# =============================================================================
_db_log_handler = None


def get_db_log_handler():
    """Return the active DatabaseLogHandler, or None."""
    return _db_log_handler


# =============================================================================
# Global Session Logger
# =============================================================================
_session_logger: Optional[SessionLogger] = None

def get_session_logger(machine_id: str = "") -> SessionLogger:
    """Get or create the global SessionLogger instance."""
    global _session_logger
    if _session_logger is None:
        _session_logger = SessionLogger(machine_id)
    return _session_logger


def set_session_logger_machine_id(machine_id: str):
    """Set the machine ID for the session logger and DB log handler."""
    global _session_logger
    if _session_logger is None:
        _session_logger = SessionLogger(machine_id)
    else:
        _session_logger.machine_id = machine_id

    if _db_log_handler is not None:
        _db_log_handler.set_machine_id(machine_id)


# =============================================================================
# Test
# =============================================================================
if __name__ == "__main__":
    # Setup logging
    setup_logging(machine_id="TEST01")
    
    logger = get_logger(__name__)
    logger.info("Test log message")
    logger.warning("Test warning")
    logger.error("Test error")
    
    # Test session logger
    session_log = get_session_logger("TEST01")
    session_log.start_session("small", "QR123")
    session_log.log_params(sval=120, cval=120, dval=60)
    session_log.log_stage("Shampoo", "Starting shampoo cycle")
    session_log.log_stage("Water", "Rinsing")
    session_log.end_session("completed")
    
    print(f"\nLog file: {get_log_file_path('TEST01')}")
