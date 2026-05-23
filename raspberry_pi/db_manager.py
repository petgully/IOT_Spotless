"""
=============================================================================
Database Manager - Project Spotless
=============================================================================
Core database connection and session-config queries.

Booking queries  -> see db_bookings.py
Session logging  -> see db_sessions.py

Configuration is loaded from environment variables (.env file):
    SPOTLESS_DB_HOST, SPOTLESS_DB_PORT, SPOTLESS_DB_USER,
    SPOTLESS_DB_PASSWORD, SPOTLESS_DB_NAME, SPOTLESS_DB_SSL
=============================================================================
"""

import os
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logger.warning("pymysql not installed. Database features disabled.")


# =============================================================================
# Database Configuration
# =============================================================================
@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    host: str = ""
    port: int = 3306
    user: str = ""
    password: str = ""
    database: str = "petgully_db"
    charset: str = "utf8mb4"
    connect_timeout: int = 10
    read_timeout: int = 30
    write_timeout: int = 30
    ssl_enabled: bool = True

    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        """Load configuration from environment variables."""
        return cls(
            host=os.environ.get('SPOTLESS_DB_HOST', ''),
            port=int(os.environ.get('SPOTLESS_DB_PORT', '3306')),
            user=os.environ.get('SPOTLESS_DB_USER', ''),
            password=os.environ.get('SPOTLESS_DB_PASSWORD', ''),
            database=os.environ.get('SPOTLESS_DB_NAME', 'petgully_db'),
            ssl_enabled=os.environ.get('SPOTLESS_DB_SSL', 'true').lower() == 'true',
        )


DEFAULT_DB_CONFIG = DatabaseConfig.from_env()


# =============================================================================
# Database Manager
# =============================================================================
class DatabaseManager:
    """
    Manages the MySQL connection and provides session-config queries.

    Usage:
        db = DatabaseManager()
        if db.connect():
            config = db.get_session_config("9876543210")
        db.disconnect()
    """

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DEFAULT_DB_CONFIG
        self._connection = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        if not self._connection:
            return False
        try:
            self._connection.ping(reconnect=False)
            return True
        except Exception:
            return False

    def connect(self) -> bool:
        if not PYMYSQL_AVAILABLE:
            logger.error("pymysql not available.")
            return False

        if not self.config.host:
            logger.error("Database host not configured. Set SPOTLESS_DB_HOST.")
            return False

        try:
            ssl_config = {'ssl': {'ssl': True}} if self.config.ssl_enabled else {}
            self._connection = pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                database=self.config.database,
                charset=self.config.charset,
                connect_timeout=self.config.connect_timeout,
                read_timeout=self.config.read_timeout,
                write_timeout=self.config.write_timeout,
                cursorclass=DictCursor,
                autocommit=True,
                **ssl_config,
            )
            self._connected = True
            logger.info(f"Connected to database: {self.config.host}")
            return True
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
            self._connected = False
            logger.info("Disconnected from database")

    def _ensure_connection(self) -> bool:
        if not self.is_connected:
            return self.connect()
        return True

    # =========================================================================
    # Session Configuration Queries
    # =========================================================================

    def get_session_config(self, mobile_number: str) -> Optional[Dict]:
        """Get session config by mobile number / QR key."""
        if not self._ensure_connection():
            return None
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    SELECT mobile_number, customer_name, session_type,
                           sval, cval, dval, wval, dryval, fval,
                           wt, stval, msgval, tdry, pr, ctype, is_active
                    FROM session_config
                    WHERE mobile_number = %s AND is_active = TRUE
                """, (mobile_number,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"get_session_config error: {e}")
            return None

    def get_session_by_type(self, session_type: str) -> Optional[Dict]:
        """Get default session config by type (uses DEFAULT_{TYPE} key)."""
        if not self._ensure_connection():
            return None
        try:
            with self._connection.cursor() as cursor:
                preset_key = f"DEFAULT_{session_type.upper()}"
                cursor.execute("""
                    SELECT mobile_number, customer_name, session_type,
                           sval, cval, dval, wval, dryval, fval,
                           wt, stval, msgval, tdry, pr, ctype
                    FROM session_config
                    WHERE mobile_number = %s
                """, (preset_key,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"get_session_by_type error: {e}")
            return None

    def create_session_config(self, mobile_number: str, customer_name: str,
                              session_type: str = "small", **params) -> bool:
        """Create or update a session_config row."""
        if not self._ensure_connection():
            return False
        try:
            defaults = {
                'sval': 120, 'cval': 120, 'dval': 60, 'wval': 60,
                'dryval': 480, 'fval': 60, 'wt': 30, 'stval': 10,
                'msgval': 10, 'tdry': 30, 'pr': 20, 'ctype': 100,
            }
            defaults.update(params)
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO session_config
                        (mobile_number, customer_name, session_type,
                         sval, cval, dval, wval, dryval, fval,
                         wt, stval, msgval, tdry, pr, ctype)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        customer_name = VALUES(customer_name),
                        session_type = VALUES(session_type),
                        sval = VALUES(sval), cval = VALUES(cval),
                        dval = VALUES(dval), wval = VALUES(wval),
                        dryval = VALUES(dryval), fval = VALUES(fval),
                        wt = VALUES(wt), stval = VALUES(stval),
                        msgval = VALUES(msgval), tdry = VALUES(tdry),
                        pr = VALUES(pr), ctype = VALUES(ctype),
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    mobile_number, customer_name, session_type,
                    defaults['sval'], defaults['cval'], defaults['dval'],
                    defaults['wval'], defaults['dryval'], defaults['fval'],
                    defaults['wt'], defaults['stval'], defaults['msgval'],
                    defaults['tdry'], defaults['pr'], defaults['ctype'],
                ))
                logger.info(f"Upserted session config for: {mobile_number}")
                return True
        except Exception as e:
            logger.error(f"create_session_config error: {e}")
            return False

    def test_connection(self) -> bool:
        if self.connect():
            logger.info("Database connection test: SUCCESS")
            return True
        logger.error("Database connection test: FAILED")
        return False


# =============================================================================
# Global Instance
# =============================================================================
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get or create the global DatabaseManager instance."""
    global _db_manager
    if _db_manager is None:
        config = DatabaseConfig.from_env()
        _db_manager = DatabaseManager(config)
    return _db_manager


# =============================================================================
# Test
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("\n" + "=" * 60)
    print("  Database Manager Test")
    print("=" * 60)

    if not PYMYSQL_AVAILABLE:
        print("\nERROR: pymysql is not installed.")
        print("Install with: pip install pymysql")
        exit(1)

    db = get_db_manager()
    print(f"\nHost: {db.config.host}")
    print(f"User: {db.config.user}")
    print(f"Database: {db.config.database}")

    if not db.config.host:
        print("\nWARNING: SPOTLESS_DB_HOST not set.")
        exit(1)

    print("\nTesting connection...")
    if db.test_connection():
        print("SUCCESS")
        config = db.get_session_config("DEFAULT_SMALL")
        if config:
            print(f"Found preset: {config}")
        db.disconnect()
    else:
        print("FAILED")
