"""
=============================================================================
Database Manager - Project Spotless
=============================================================================
Handles AWS RDS Aurora MySQL connectivity for session configuration.

Features:
- Fetch session parameters by mobile number or QR code
- Log session activity
- Offline fallback support
- Connection pooling and retry logic

Configuration:
- Database credentials stored in environment variables or .env file
- SSL enabled for secure connections
=============================================================================
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import pymysql
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logger.warning("pymysql not installed. Database features disabled.")
    logger.warning("Install with: pip install pymysql")


# =============================================================================
# Database Configuration
# =============================================================================
@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    host: str = ""
    port: int = 3306
    user: str = "spotless001"
    password: str = "Batman@686"
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
            user=os.environ.get('SPOTLESS_DB_USER', 'spotless001'),
            password=os.environ.get('SPOTLESS_DB_PASSWORD', 'Batman@686'),
            database=os.environ.get('SPOTLESS_DB_NAME', 'petgully_db'),
            ssl_enabled=os.environ.get('SPOTLESS_DB_SSL', 'true').lower() == 'true',
        )


# Default configuration - PetGully Aurora RDS
DEFAULT_DB_CONFIG = DatabaseConfig(
    host="petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com",
    port=3306,
    user="spotless001",
    password="Batman@686",
    database="petgully_db",
)


# =============================================================================
# Database Manager Class
# =============================================================================
class DatabaseManager:
    """
    Manages database connections and queries for Spotless.
    
    Usage:
        db = DatabaseManager()
        
        # Connect
        if db.connect():
            # Fetch session config
            config = db.get_session_config("9876543210")
            
            # Log session
            db.log_session_start("9876543210", "BS01", "small", "QR123")
            
        # Disconnect
        db.disconnect()
    """
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize database manager.
        
        Args:
            config: Database configuration (uses default if not provided)
        """
        self.config = config or DEFAULT_DB_CONFIG
        self._connection = None
        self._connected = False
        
    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        if not self._connection:
            return False
        try:
            self._connection.ping(reconnect=False)
            return True
        except:
            return False
            
    def connect(self) -> bool:
        """
        Connect to the database.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if not PYMYSQL_AVAILABLE:
            logger.error("pymysql not available. Cannot connect to database.")
            return False
            
        if not self.config.host:
            logger.error("Database host not configured. Set SPOTLESS_DB_HOST environment variable.")
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
                **ssl_config
            )
            
            self._connected = True
            logger.info(f"Connected to database: {self.config.host}")
            return True
            
        except pymysql.Error as e:
            logger.error(f"Database connection error: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to database: {e}")
            self._connected = False
            return False
            
    def disconnect(self):
        """Disconnect from the database."""
        if self._connection:
            try:
                self._connection.close()
            except:
                pass
            self._connection = None
            self._connected = False
            logger.info("Disconnected from database")
            
    def _ensure_connection(self) -> bool:
        """Ensure database connection is active."""
        if not self.is_connected:
            return self.connect()
        return True
        
    # =========================================================================
    # Session Configuration Queries
    # =========================================================================
    
    def get_session_config(self, mobile_number: str) -> Optional[Dict]:
        """
        Get session configuration by mobile number.
        
        Args:
            mobile_number: Customer's mobile number
            
        Returns:
            Dictionary with session parameters or None if not found
        """
        if not self._ensure_connection():
            return None
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    SELECT 
                        mobile_number, customer_name, session_type,
                        sval, cval, dval, wval, dryval, fval,
                        wt, stval, msgval, tdry, pr, ctype,
                        is_active
                    FROM session_config
                    WHERE mobile_number = %s AND is_active = TRUE
                """
                cursor.execute(sql, (mobile_number,))
                result = cursor.fetchone()
                
                if result:
                    logger.info(f"Found session config for: {mobile_number}")
                    return dict(result)
                else:
                    logger.warning(f"No session config found for: {mobile_number}")
                    return None
                    
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return None
            
    def get_session_by_type(self, session_type: str) -> Optional[Dict]:
        """
        Get default session configuration by type.
        
        Args:
            session_type: Session type (small, large, custdiy, etc.)
            
        Returns:
            Dictionary with session parameters
        """
        if not self._ensure_connection():
            return None
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    SELECT 
                        mobile_number, customer_name, session_type,
                        sval, cval, dval, wval, dryval, fval,
                        wt, stval, msgval, tdry, pr, ctype
                    FROM session_config
                    WHERE mobile_number = %s
                """
                # Use default presets
                preset_key = f"DEFAULT_{session_type.upper()}"
                cursor.execute(sql, (preset_key,))
                result = cursor.fetchone()
                
                return dict(result) if result else None
                    
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return None
            
    def create_session_config(self, mobile_number: str, customer_name: str,
                               session_type: str = "small", **params) -> bool:
        """
        Create or update session configuration for a customer.
        
        Args:
            mobile_number: Customer's mobile number
            customer_name: Customer's name
            session_type: Session type
            **params: Additional session parameters (sval, cval, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                # Use INSERT ... ON DUPLICATE KEY UPDATE
                sql = """
                    INSERT INTO session_config 
                        (mobile_number, customer_name, session_type,
                         sval, cval, dval, wval, dryval, fval,
                         wt, stval, msgval, tdry, pr, ctype)
                    VALUES 
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        customer_name = VALUES(customer_name),
                        session_type = VALUES(session_type),
                        sval = VALUES(sval),
                        cval = VALUES(cval),
                        dval = VALUES(dval),
                        wval = VALUES(wval),
                        dryval = VALUES(dryval),
                        fval = VALUES(fval),
                        wt = VALUES(wt),
                        stval = VALUES(stval),
                        msgval = VALUES(msgval),
                        tdry = VALUES(tdry),
                        pr = VALUES(pr),
                        ctype = VALUES(ctype),
                        updated_at = CURRENT_TIMESTAMP
                """
                
                # Default values
                defaults = {
                    'sval': 120, 'cval': 120, 'dval': 60, 'wval': 60,
                    'dryval': 480, 'fval': 60, 'wt': 30, 'stval': 10,
                    'msgval': 10, 'tdry': 30, 'pr': 20, 'ctype': 100
                }
                defaults.update(params)
                
                cursor.execute(sql, (
                    mobile_number, customer_name, session_type,
                    defaults['sval'], defaults['cval'], defaults['dval'],
                    defaults['wval'], defaults['dryval'], defaults['fval'],
                    defaults['wt'], defaults['stval'], defaults['msgval'],
                    defaults['tdry'], defaults['pr'], defaults['ctype']
                ))
                
                logger.info(f"Created/updated session config for: {mobile_number}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database insert error: {e}")
            return False
            
    # =========================================================================
    # Session Logging - Comprehensive Tracking
    # =========================================================================
    
    def log_session_activated(self, mobile_number: str, machine_id: str,
                               session_type: str, qr_code: str,
                               params: Dict = None) -> Optional[int]:
        """
        Log when a session is activated (QR scanned).
        
        Args:
            mobile_number: Customer's mobile number
            machine_id: Machine/booth ID
            session_type: Session type
            qr_code: QR code used
            params: All session parameters
            
        Returns:
            Session log ID or None if failed
        """
        if not self._ensure_connection():
            return None
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    INSERT INTO session_logs 
                        (mobile_number, machine_id, session_type, qr_code,
                         activated_at, status,
                         sval, cval, dval, wval, dryval, fval,
                         wt, stval, msgval, tdry, pr, ctype)
                    VALUES 
                        (%s, %s, %s, %s, NOW(), 'activated',
                         %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                params = params or {}
                cursor.execute(sql, (
                    mobile_number, machine_id, session_type, qr_code,
                    params.get('sval'), params.get('cval'),
                    params.get('dval'), params.get('wval'),
                    params.get('dryval'), params.get('fval'),
                    params.get('wt'), params.get('stval'),
                    params.get('msgval'), params.get('tdry'),
                    params.get('pr'), params.get('ctype')
                ))
                
                session_id = cursor.lastrowid
                logger.info(f"Session activated - ID: {session_id}, Mobile: {mobile_number}, Type: {session_type}")
                return session_id
                
        except pymysql.Error as e:
            logger.error(f"Database insert error: {e}")
            return None
    
    def log_session_start(self, session_id: int) -> bool:
        """
        Log when session actually starts running.
        
        Args:
            session_id: Session log ID from log_session_activated
            
        Returns:
            True if successful
        """
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_logs 
                    SET session_start = NOW(), status = 'started'
                    WHERE id = %s
                """
                cursor.execute(sql, (session_id,))
                logger.info(f"Session started - ID: {session_id}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
    
    def log_session_in_progress(self, session_id: int) -> bool:
        """Mark session as in progress."""
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = "UPDATE session_logs SET status = 'in_progress' WHERE id = %s"
                cursor.execute(sql, (session_id,))
                return True
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
            
    def log_session_complete(self, session_id: int, duration_seconds: int) -> bool:
        """
        Log the completion of a session.
        
        Args:
            session_id: Session log ID
            duration_seconds: Total session duration
            
        Returns:
            True if successful
        """
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_logs 
                    SET session_end = NOW(), 
                        total_duration_seconds = %s,
                        status = 'completed'
                    WHERE id = %s
                """
                cursor.execute(sql, (duration_seconds, session_id))
                logger.info(f"Session completed - ID: {session_id}, Duration: {duration_seconds}s")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
            
    def log_session_error(self, session_id: int, error_message: str = "") -> bool:
        """Log a session error."""
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_logs 
                    SET session_end = NOW(), 
                        status = 'error',
                        error_message = %s
                    WHERE id = %s
                """
                cursor.execute(sql, (error_message, session_id))
                logger.info(f"Session error - ID: {session_id}, Error: {error_message}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
    
    def log_session_stopped(self, session_id: int, duration_seconds: int = None) -> bool:
        """Log when session is manually stopped (emergency stop)."""
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_logs 
                    SET session_end = NOW(), 
                        status = 'stopped',
                        total_duration_seconds = %s
                    WHERE id = %s
                """
                cursor.execute(sql, (duration_seconds, session_id))
                logger.info(f"Session stopped - ID: {session_id}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
    
    # =========================================================================
    # Stage Logging - Track each stage (shampoo, conditioner, etc.)
    # =========================================================================
    
    def log_stage_start(self, session_id: int, stage_name: str, 
                        stage_order: int, planned_duration: int) -> Optional[int]:
        """
        Log the start of a stage.
        
        Args:
            session_id: Parent session ID
            stage_name: Name of stage (shampoo, conditioner, water, dryer, etc.)
            stage_order: Order in session (1, 2, 3...)
            planned_duration: Configured duration in seconds
            
        Returns:
            Stage ID or None if failed
        """
        if not self._ensure_connection():
            return None
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    INSERT INTO session_stages 
                        (session_id, stage_name, stage_order, 
                         planned_duration_seconds, start_time, status)
                    VALUES 
                        (%s, %s, %s, %s, NOW(), 'started')
                """
                cursor.execute(sql, (session_id, stage_name, stage_order, planned_duration))
                stage_id = cursor.lastrowid
                logger.info(f"Stage started - Session: {session_id}, Stage: {stage_name}, Order: {stage_order}")
                return stage_id
                
        except pymysql.Error as e:
            logger.error(f"Database insert error: {e}")
            return None
    
    def log_stage_complete(self, stage_id: int, actual_duration: int) -> bool:
        """
        Log the completion of a stage.
        
        Args:
            stage_id: Stage ID from log_stage_start
            actual_duration: Actual duration in seconds
            
        Returns:
            True if successful
        """
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_stages 
                    SET end_time = NOW(), 
                        actual_duration_seconds = %s,
                        status = 'completed'
                    WHERE id = %s
                """
                cursor.execute(sql, (actual_duration, stage_id))
                logger.info(f"Stage completed - ID: {stage_id}, Duration: {actual_duration}s")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
    
    def log_stage_skipped(self, session_id: int, stage_name: str, 
                          stage_order: int, reason: str = None) -> bool:
        """Log when a stage is skipped."""
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    INSERT INTO session_stages 
                        (session_id, stage_name, stage_order, status, notes)
                    VALUES 
                        (%s, %s, %s, 'skipped', %s)
                """
                cursor.execute(sql, (session_id, stage_name, stage_order, reason))
                logger.info(f"Stage skipped - Session: {session_id}, Stage: {stage_name}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database insert error: {e}")
            return False
    
    def log_stage_error(self, stage_id: int, error_message: str) -> bool:
        """Log a stage error."""
        if not self._ensure_connection():
            return False
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    UPDATE session_stages 
                    SET end_time = NOW(), 
                        status = 'error',
                        notes = %s
                    WHERE id = %s
                """
                cursor.execute(sql, (error_message, stage_id))
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database update error: {e}")
            return False
    
    # =========================================================================
    # Event Logging - Granular tracking for debugging/audit
    # =========================================================================
    
    def log_event(self, session_id: int, event_type: str, 
                  event_data: Dict = None) -> bool:
        """
        Log a granular event.
        
        Args:
            session_id: Parent session ID
            event_type: Type of event (relay_on, relay_off, pump_start, etc.)
            event_data: Additional JSON data
            
        Returns:
            True if successful
        """
        if not self._ensure_connection():
            return False
            
        try:
            import json
            with self._connection.cursor() as cursor:
                sql = """
                    INSERT INTO session_events 
                        (session_id, event_type, event_data)
                    VALUES 
                        (%s, %s, %s)
                """
                event_json = json.dumps(event_data) if event_data else None
                cursor.execute(sql, (session_id, event_type, event_json))
                return True
                
        except pymysql.Error as e:
            logger.error(f"Database insert error: {e}")
            return False
            
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def test_connection(self) -> bool:
        """Test database connection."""
        if self.connect():
            logger.info("Database connection test: SUCCESS")
            return True
        else:
            logger.error("Database connection test: FAILED")
            return False
            
    def get_session_history(self, mobile_number: str, limit: int = 10) -> List[Dict]:
        """Get session history for a customer."""
        if not self._ensure_connection():
            return []
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    SELECT * FROM session_logs
                    WHERE mobile_number = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """
                cursor.execute(sql, (mobile_number, limit))
                return [dict(row) for row in cursor.fetchall()]
                
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return []
    
    def get_session_details(self, session_id: int) -> Optional[Dict]:
        """
        Get complete session details including stages and events.
        
        Returns:
            Dictionary with session, stages, and events data
        """
        if not self._ensure_connection():
            return None
            
        try:
            result = {}
            
            with self._connection.cursor() as cursor:
                # Get session
                cursor.execute("SELECT * FROM session_logs WHERE id = %s", (session_id,))
                result['session'] = cursor.fetchone()
                
                if not result['session']:
                    return None
                
                # Get stages
                cursor.execute("""
                    SELECT * FROM session_stages 
                    WHERE session_id = %s 
                    ORDER BY stage_order
                """, (session_id,))
                result['stages'] = cursor.fetchall()
                
                # Get events
                cursor.execute("""
                    SELECT * FROM session_events 
                    WHERE session_id = %s 
                    ORDER BY event_time
                """, (session_id,))
                result['events'] = cursor.fetchall()
                
            return result
            
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return None
    
    def get_machine_stats(self, machine_id: str, days: int = 30) -> Dict:
        """
        Get statistics for a machine.
        
        Args:
            machine_id: Machine ID
            days: Number of days to look back
            
        Returns:
            Dictionary with statistics
        """
        if not self._ensure_connection():
            return {}
            
        try:
            stats = {}
            
            with self._connection.cursor() as cursor:
                # Total sessions
                cursor.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                           SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                           AVG(total_duration_seconds) as avg_duration
                    FROM session_logs 
                    WHERE machine_id = %s 
                    AND activated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                """, (machine_id, days))
                stats['sessions'] = cursor.fetchone()
                
                # Sessions by type
                cursor.execute("""
                    SELECT session_type, COUNT(*) as count
                    FROM session_logs 
                    WHERE machine_id = %s 
                    AND activated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    GROUP BY session_type
                """, (machine_id, days))
                stats['by_type'] = cursor.fetchall()
                
            return stats
            
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return {}
    
    def get_stage_analytics(self, session_type: str = None, days: int = 30) -> List[Dict]:
        """
        Get analytics on stage durations for optimization.
        
        Returns:
            List of stage statistics (avg planned vs actual duration)
        """
        if not self._ensure_connection():
            return []
            
        try:
            with self._connection.cursor() as cursor:
                sql = """
                    SELECT 
                        ss.stage_name,
                        COUNT(*) as total_executions,
                        AVG(ss.planned_duration_seconds) as avg_planned,
                        AVG(ss.actual_duration_seconds) as avg_actual,
                        MIN(ss.actual_duration_seconds) as min_actual,
                        MAX(ss.actual_duration_seconds) as max_actual,
                        SUM(CASE WHEN ss.status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN ss.status = 'error' THEN 1 ELSE 0 END) as errors
                    FROM session_stages ss
                    JOIN session_logs sl ON ss.session_id = sl.id
                    WHERE sl.activated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                """
                
                if session_type:
                    sql += " AND sl.session_type = %s"
                    sql += " GROUP BY ss.stage_name ORDER BY ss.stage_name"
                    cursor.execute(sql, (days, session_type))
                else:
                    sql += " GROUP BY ss.stage_name ORDER BY ss.stage_name"
                    cursor.execute(sql, (days,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return []


# =============================================================================
# Global Instance
# =============================================================================
_db_manager: Optional[DatabaseManager] = None

def get_db_manager() -> DatabaseManager:
    """Get or create the global DatabaseManager instance."""
    global _db_manager
    if _db_manager is None:
        # Try to load config from environment
        config = DatabaseConfig.from_env()
        _db_manager = DatabaseManager(config)
    return _db_manager


def set_db_config(host: str, port: int = 3306, user: str = "spotless001",
                  password: str = "Batman@686", database: str = "petgully_db"):
    """Set database configuration."""
    global _db_manager
    config = DatabaseConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )
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
    
    # Check if pymysql is available
    if not PYMYSQL_AVAILABLE:
        print("\nERROR: pymysql is not installed.")
        print("Install with: pip install pymysql")
        exit(1)
    
    # Get config from environment or use defaults
    db = get_db_manager()
    
    print(f"\nDatabase Host: {db.config.host}")
    print(f"Database User: {db.config.user}")
    print(f"Database Name: {db.config.database}")
    
    if not db.config.host or db.config.host.startswith("your-"):
        print("\nWARNING: Database host not configured!")
        print("Set the SPOTLESS_DB_HOST environment variable:")
        print("  export SPOTLESS_DB_HOST=your-aurora-endpoint.cluster-xxxxx.region.rds.amazonaws.com")
        exit(1)
    
    # Test connection
    print("\nTesting connection...")
    if db.test_connection():
        print("SUCCESS: Connected to database!")
        
        # Test query
        print("\nTesting query...")
        config = db.get_session_config("DEFAULT_SMALL")
        if config:
            print(f"Found preset: {config}")
        
        db.disconnect()
    else:
        print("FAILED: Could not connect to database.")
        print("\nCheck:")
        print("1. Aurora endpoint is correct")
        print("2. Security group allows inbound from 0.0.0.0/0 on port 3306")
        print("3. Username and password are correct")
