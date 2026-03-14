"""
=============================================================================
Configuration Manager - Project Spotless
=============================================================================
Manages machine configuration with offline support.

Features:
- Local JSON configuration storage
- Machine ID management
- Session parameter configuration
- Offline fallback mode
- Ready for database integration

Configuration is stored in:
    ~/.spotless/config.json      - Main configuration
    ~/.spotless/machine_id.txt   - Cached machine ID
    ~/.spotless/sessions/        - Session logs (offline)
=============================================================================
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Paths
# =============================================================================
# Use home directory for config storage
CONFIG_DIR = Path.home() / ".spotless"
CONFIG_FILE = CONFIG_DIR / "config.json"
MACHINE_ID_FILE = CONFIG_DIR / "machine_id.txt"
SESSIONS_DIR = CONFIG_DIR / "sessions"
CACHE_FILE = CONFIG_DIR / "db_cache.json"


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class SessionConfig:
    """Configuration for a bath session type."""
    session_type: str
    description: str
    sval: int           # Shampoo duration (seconds)
    cval: int           # Conditioner duration (seconds)
    dval: int           # Disinfectant duration (seconds)
    wval: int           # Water duration (seconds)
    dryval: int         # Dryer duration (seconds)
    fval: int           # Flush duration (seconds)
    wt: int             # Wait/pump time (seconds)
    stval: int          # Stage value/wait time
    msgval: int         # Massage time (seconds)
    tdry: int           # Towel dry time (seconds)
    pr: int             # Process type (10 = include disinfectant)
    ctype: int          # Conditioner type (100=normal, 200=medicated)
    stage: int = 1      # Starting stage
    handler: str = "Spotless"  # Function handler name
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SessionConfig':
        return cls(**data)
    
    def get_params(self) -> Dict:
        """Get parameters for Spotless function (excluding session_type, description, handler)."""
        params = self.to_dict()
        params.pop('session_type', None)
        params.pop('description', None)
        params.pop('handler', None)
        return params


@dataclass
class UtilityConfig:
    """Configuration for utility/test sessions (simpler structure)."""
    session_type: str
    description: str
    handler: str        # Function to call (Dryer, Flush, etc.)
    duration: int = 0   # Duration in seconds (if applicable)
    needs_qr: bool = False  # Whether QR/session ID is needed
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UtilityConfig':
        return cls(**data)
    
    def get_params(self) -> Dict:
        """Get parameters for the handler function."""
        params = {}
        if self.duration > 0:
            params['duration'] = self.duration
        return params


@dataclass
class MachineConfig:
    """Configuration for a specific machine/booth."""
    machine_id: str
    machine_name: str
    location: str
    is_active: bool
    session_configs: Dict[str, SessionConfig]
    utility_configs: Dict[str, UtilityConfig]
    created_at: str
    updated_at: str
    
    def to_dict(self) -> Dict:
        data = {
            'machine_id': self.machine_id,
            'machine_name': self.machine_name,
            'location': self.location,
            'is_active': self.is_active,
            'session_configs': {k: v.to_dict() for k, v in self.session_configs.items()},
            'utility_configs': {k: v.to_dict() for k, v in self.utility_configs.items()},
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MachineConfig':
        session_configs = {
            k: SessionConfig.from_dict(v) 
            for k, v in data.get('session_configs', {}).items()
        }
        utility_configs = {
            k: UtilityConfig.from_dict(v) 
            for k, v in data.get('utility_configs', {}).items()
        }
        return cls(
            machine_id=data['machine_id'],
            machine_name=data['machine_name'],
            location=data['location'],
            is_active=data.get('is_active', True),
            session_configs=session_configs,
            utility_configs=utility_configs,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
        )


class ConfigSource(Enum):
    """Source of configuration."""
    LOCAL = "local"
    DATABASE = "database"
    DEFAULT = "default"


# =============================================================================
# Default Configurations
# =============================================================================
DEFAULT_SESSION_CONFIGS = {
    # Full bath sessions - use Spotless function
    "small": SessionConfig(
        session_type="small",
        description="Small Pet Bath Session",
        sval=120, cval=120, dval=60, wval=60, dryval=480, fval=60,
        wt=30, stval=10, msgval=10, tdry=30, pr=20, ctype=100, stage=1,
        handler="Spotless"
    ),
    "large": SessionConfig(
        session_type="large",
        description="Large Pet Bath Session",
        sval=150, cval=150, dval=60, wval=80, dryval=600, fval=60,
        wt=50, stval=10, msgval=10, tdry=30, pr=20, ctype=100, stage=1,
        handler="Spotless"
    ),
    "custdiy": SessionConfig(
        session_type="custdiy",
        description="Customer DIY Session",
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=12, stval=10, msgval=10, tdry=30, pr=10, ctype=100, stage=1,
        handler="Spotless"
    ),
    "medsmall": SessionConfig(
        session_type="medsmall",
        description="Medicated Bath - Small Pet",
        sval=80, cval=80, dval=60, wval=60, dryval=480, fval=60,
        wt=30, stval=10, msgval=10, tdry=30, pr=20, ctype=200, stage=1,
        handler="Spotless"
    ),
    "medlarge": SessionConfig(
        session_type="medlarge",
        description="Medicated Bath - Large Pet",
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=50, stval=10, msgval=10, tdry=30, pr=20, ctype=200, stage=1,
        handler="Spotless"
    ),
    "onlydisinfectant": SessionConfig(
        session_type="onlydisinfectant",
        description="Disinfectant Only",
        sval=100, cval=100, dval=60, wval=60, dryval=600, fval=60,
        wt=15, stval=10, msgval=10, tdry=30, pr=20, ctype=200, stage=1,
        handler="fromDisinfectant"
    ),
}

# Utility sessions - simpler configurations with specific handler functions
DEFAULT_UTILITY_CONFIGS = {
    "quicktest": UtilityConfig(
        session_type="quicktest",
        description="Quick Relay Test",
        handler="test_relays",
        duration=0,
        needs_qr=True
    ),
    "onlydrying": UtilityConfig(
        session_type="onlydrying",
        description="Dryer Only (5 min)",
        handler="Dryer",
        duration=300,
        needs_qr=True
    ),
    "onlywater": UtilityConfig(
        session_type="onlywater",
        description="Water Only (90s)",
        handler="just_water",
        duration=90,
        needs_qr=False
    ),
    "onlyflush": UtilityConfig(
        session_type="onlyflush",
        description="Flush Only (60s)",
        handler="Flush",
        duration=60,
        needs_qr=False
    ),
    "onlyshampoo": UtilityConfig(
        session_type="onlyshampoo",
        description="Shampoo Only",
        handler="just_shampoo",
        duration=0,
        needs_qr=True
    ),
    "empty001": UtilityConfig(
        session_type="empty001",
        description="Empty Tank (3 min)",
        handler="Empty_tank",
        duration=180,
        needs_qr=False
    ),
    "demo": UtilityConfig(
        session_type="demo",
        description="Demo Mode - Sequential Relay Test",
        handler="demo",
        duration=0,
        needs_qr=True
    ),
}


def create_default_machine_config(machine_id: str) -> MachineConfig:
    """Create a default machine configuration."""
    now = datetime.now().isoformat()
    return MachineConfig(
        machine_id=machine_id,
        machine_name=f"Spotless Booth {machine_id}",
        location="Not configured",
        is_active=True,
        session_configs=DEFAULT_SESSION_CONFIGS.copy(),
        utility_configs=DEFAULT_UTILITY_CONFIGS.copy(),
        created_at=now,
        updated_at=now,
    )


# =============================================================================
# Configuration Manager
# =============================================================================
class ConfigManager:
    """
    Manages machine configuration with offline support.
    
    Usage:
        config_mgr = ConfigManager()
        
        # Get or prompt for machine ID
        machine_id = config_mgr.get_machine_id()
        
        # Load configuration
        config = config_mgr.load_config()
        
        # Get session parameters
        params = config_mgr.get_session_params("small")
    """
    
    def __init__(self):
        self._machine_id: Optional[str] = None
        self._config: Optional[MachineConfig] = None
        self._config_source: ConfigSource = ConfigSource.DEFAULT
        self._db_manager = None  # Will be set when database is configured
        
        # Ensure config directories exist
        self._ensure_directories()
        
    def _ensure_directories(self):
        """Ensure configuration directories exist."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        
    # =========================================================================
    # Machine ID Management
    # =========================================================================
    
    def get_machine_id(self, prompt_if_missing: bool = True) -> Optional[str]:
        """
        Get the machine ID.
        
        Priority:
        1. Already loaded in memory
        2. Saved in machine_id.txt
        3. Prompt user (if prompt_if_missing=True)
        """
        # Check if already loaded
        if self._machine_id:
            return self._machine_id
            
        # Try to load from file
        if MACHINE_ID_FILE.exists():
            try:
                self._machine_id = MACHINE_ID_FILE.read_text().strip()
                if self._machine_id:
                    logger.info(f"Loaded machine ID from file: {self._machine_id}")
                    return self._machine_id
            except Exception as e:
                logger.warning(f"Error reading machine ID file: {e}")
                
        # Prompt user
        if prompt_if_missing:
            self._machine_id = self._prompt_machine_id()
            if self._machine_id:
                self.save_machine_id(self._machine_id)
                
        return self._machine_id
        
    def _prompt_machine_id(self) -> Optional[str]:
        """Prompt user for machine ID."""
        print("\n" + "=" * 50)
        print("  SPOTLESS - Machine Configuration")
        print("=" * 50)
        print("\nNo machine ID configured.")
        print("Please enter the Machine ID for this booth.")
        print("(e.g., BS01, BS02, HONER01)")
        print("")
        
        while True:
            machine_id = input("Machine ID: ").strip().upper()
            
            if not machine_id:
                print("Machine ID cannot be empty. Please try again.")
                continue
                
            if len(machine_id) < 2:
                print("Machine ID must be at least 2 characters. Please try again.")
                continue
                
            # Confirm
            confirm = input(f"Confirm Machine ID '{machine_id}'? (y/n): ").strip().lower()
            if confirm == 'y':
                return machine_id
            print("Let's try again.\n")
            
    def save_machine_id(self, machine_id: str):
        """Save machine ID to file."""
        try:
            MACHINE_ID_FILE.write_text(machine_id)
            self._machine_id = machine_id
            logger.info(f"Saved machine ID: {machine_id}")
        except Exception as e:
            logger.error(f"Error saving machine ID: {e}")
            
    def clear_machine_id(self):
        """Clear saved machine ID."""
        try:
            if MACHINE_ID_FILE.exists():
                MACHINE_ID_FILE.unlink()
            self._machine_id = None
            logger.info("Cleared machine ID")
        except Exception as e:
            logger.error(f"Error clearing machine ID: {e}")
            
    # =========================================================================
    # Configuration Loading
    # =========================================================================
    
    def load_config(self, force_reload: bool = False) -> MachineConfig:
        """
        Load configuration for the current machine.
        
        Priority:
        1. Database (when connected)
        2. Local config file
        3. Default configuration
        """
        if self._config and not force_reload:
            return self._config
            
        machine_id = self.get_machine_id()
        if not machine_id:
            raise ValueError("Machine ID not configured")
            
        # Try database first (when implemented)
        if self._db_manager:
            try:
                self._config = self._load_from_database(machine_id)
                if self._config:
                    self._config_source = ConfigSource.DATABASE
                    # Cache to local file
                    self._save_to_local(self._config)
                    logger.info(f"Loaded config from DATABASE for {machine_id}")
                    return self._config
            except Exception as e:
                logger.warning(f"Database unavailable: {e}. Falling back to local config.")
                
        # Try local config file
        local_config = self._load_from_local(machine_id)
        if local_config:
            self._config = local_config
            self._config_source = ConfigSource.LOCAL
            logger.info(f"Loaded config from LOCAL file for {machine_id}")
            return self._config
            
        # Use default configuration
        self._config = create_default_machine_config(machine_id)
        self._config_source = ConfigSource.DEFAULT
        self._save_to_local(self._config)
        logger.info(f"Using DEFAULT config for {machine_id}")
        return self._config
        
    def _load_from_database(self, machine_id: str) -> Optional[MachineConfig]:
        """Load configuration from database."""
        if not self._db_manager:
            return None
            
        try:
            # Try to fetch session configs from database
            # For now, we just validate connection
            # Full implementation would fetch machine-specific configs
            from db_manager import get_db_manager
            db = get_db_manager()
            
            if db.connect():
                # Database is available
                # Configs are fetched per-session based on QR/mobile
                # Machine config uses local/default for now
                logger.info("Database connection available")
                db.disconnect()
                
            return None  # Use local config, DB is for per-session lookups
            
        except Exception as e:
            logger.warning(f"Database load failed: {e}")
            return None
        
    def _load_from_local(self, machine_id: str) -> Optional[MachineConfig]:
        """Load configuration from local file."""
        if not CONFIG_FILE.exists():
            return None
            
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                
            # Check if it's for the right machine
            if data.get('machine_id') == machine_id:
                config = MachineConfig.from_dict(data)
                
                # Merge any new default utility configs that might have been added
                updated = False
                for key, util_config in DEFAULT_UTILITY_CONFIGS.items():
                    if key not in config.utility_configs:
                        config.utility_configs[key] = util_config
                        logger.info(f"Added new utility config: {key}")
                        updated = True
                
                # Merge any new default session configs that might have been added
                for key, session_config in DEFAULT_SESSION_CONFIGS.items():
                    if key not in config.session_configs:
                        config.session_configs[key] = session_config
                        logger.info(f"Added new session config: {key}")
                        updated = True
                
                # Save updated config if new entries were added
                if updated:
                    self._save_to_local(config)
                    logger.info("Updated local config with new default entries")
                
                return config
            else:
                logger.warning(f"Local config is for different machine: {data.get('machine_id')}")
                return None
                
        except Exception as e:
            logger.error(f"Error loading local config: {e}")
            return None
            
    def _save_to_local(self, config: MachineConfig):
        """Save configuration to local file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config.to_dict(), f, indent=2)
            logger.info(f"Saved config to local file: {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error saving local config: {e}")
            
    # =========================================================================
    # Session Configuration Access
    # =========================================================================
    
    def get_session_config(self, session_type: str) -> Optional[SessionConfig]:
        """Get configuration for a specific session type (full bath sessions)."""
        config = self.load_config()
        return config.session_configs.get(session_type)
        
    def get_utility_config(self, session_type: str) -> Optional[UtilityConfig]:
        """Get configuration for a utility session type."""
        config = self.load_config()
        return config.utility_configs.get(session_type)
        
    def get_any_config(self, session_type: str) -> Optional[Any]:
        """Get configuration for any session type (session or utility)."""
        config = self.load_config()
        if session_type in config.session_configs:
            return config.session_configs[session_type]
        if session_type in config.utility_configs:
            return config.utility_configs[session_type]
        return None
        
    def get_session_params(self, session_type: str) -> Optional[Dict]:
        """Get parameters for Spotless function."""
        session_config = self.get_session_config(session_type)
        if session_config:
            return session_config.get_params()
        return None
        
    def get_handler(self, session_type: str) -> Optional[str]:
        """Get the handler function name for a session type."""
        cfg = self.get_any_config(session_type)
        if cfg:
            return cfg.handler
        return None
        
    def is_utility_session(self, session_type: str) -> bool:
        """Check if a session type is a utility session."""
        config = self.load_config()
        return session_type in config.utility_configs
        
    def list_session_types(self) -> List[str]:
        """List available full bath session types."""
        config = self.load_config()
        return list(config.session_configs.keys())
        
    def list_utility_types(self) -> List[str]:
        """List available utility session types."""
        config = self.load_config()
        return list(config.utility_configs.keys())
        
    def list_all_session_types(self) -> List[str]:
        """List ALL available session types (both full and utility)."""
        config = self.load_config()
        return list(config.session_configs.keys()) + list(config.utility_configs.keys())
        
    def get_session_description(self, session_type: str) -> str:
        """Get description for a session type (any type)."""
        cfg = self.get_any_config(session_type)
        return cfg.description if cfg else "Unknown"
        
    # =========================================================================
    # Configuration Updates
    # =========================================================================
    
    def update_session_config(self, session_type: str, **kwargs):
        """Update a session configuration parameter."""
        config = self.load_config()
        
        if session_type not in config.session_configs:
            logger.error(f"Unknown session type: {session_type}")
            return False
            
        session_config = config.session_configs[session_type]
        
        for key, value in kwargs.items():
            if hasattr(session_config, key):
                setattr(session_config, key, value)
                logger.info(f"Updated {session_type}.{key} = {value}")
            else:
                logger.warning(f"Unknown parameter: {key}")
                
        config.updated_at = datetime.now().isoformat()
        self._save_to_local(config)
        return True
        
    def update_utility_config(self, session_type: str, **kwargs):
        """Update a utility configuration parameter."""
        config = self.load_config()
        
        if session_type not in config.utility_configs:
            logger.error(f"Unknown utility type: {session_type}")
            return False
            
        utility_config = config.utility_configs[session_type]
        
        for key, value in kwargs.items():
            if hasattr(utility_config, key):
                setattr(utility_config, key, value)
                logger.info(f"Updated {session_type}.{key} = {value}")
            else:
                logger.warning(f"Unknown parameter: {key}")
                
        config.updated_at = datetime.now().isoformat()
        self._save_to_local(config)
        return True
        
    def update_machine_info(self, **kwargs):
        """Update machine information."""
        config = self.load_config()
        
        for key, value in kwargs.items():
            if hasattr(config, key) and key not in ['session_configs', 'utility_configs']:
                setattr(config, key, value)
                logger.info(f"Updated machine.{key} = {value}")
                
        config.updated_at = datetime.now().isoformat()
        self._save_to_local(config)
        
    # =========================================================================
    # Session Logging (Offline)
    # =========================================================================
    
    def log_session(self, session_type: str, qr_code: str, 
                    start_time: datetime, end_time: datetime,
                    status: str = "completed") -> str:
        """
        Log a session (offline storage).
        
        Returns:
            Session log filename
        """
        duration = (end_time - start_time).total_seconds()
        
        log_data = {
            'machine_id': self._machine_id,
            'session_type': session_type,
            'qr_code': qr_code,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': int(duration),
            'status': status,
            'synced_to_db': False,
        }
        
        # Generate filename
        filename = f"{start_time.strftime('%Y%m%d_%H%M%S')}_{session_type}.json"
        filepath = SESSIONS_DIR / filename
        
        try:
            with open(filepath, 'w') as f:
                json.dump(log_data, f, indent=2)
            logger.info(f"Session logged: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error logging session: {e}")
            return ""
            
    def get_pending_session_logs(self) -> List[Dict]:
        """Get session logs that haven't been synced to database."""
        pending = []
        
        for filepath in SESSIONS_DIR.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                if not data.get('synced_to_db', False):
                    data['_filepath'] = str(filepath)
                    pending.append(data)
            except Exception as e:
                logger.warning(f"Error reading session log {filepath}: {e}")
                
        return pending
        
    def mark_session_synced(self, filepath: str):
        """Mark a session log as synced to database."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            data['synced_to_db'] = True
            data['synced_at'] = datetime.now().isoformat()
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error marking session synced: {e}")
            
    # =========================================================================
    # Database Manager Integration
    # =========================================================================
    
    def set_database_manager(self, db_manager):
        """Set the database manager for online mode."""
        self._db_manager = db_manager
        logger.info("Database manager connected")
        
    def sync_to_database(self) -> bool:
        """Sync local config and logs to database."""
        if not self._db_manager:
            logger.warning("Database manager not configured")
            return False
            
        # TODO: Implement database sync
        return True
        
    # =========================================================================
    # Status and Info
    # =========================================================================
    
    @property
    def config_source(self) -> ConfigSource:
        """Get the source of current configuration."""
        return self._config_source
        
    @property
    def is_online(self) -> bool:
        """Check if database is available."""
        return self._db_manager is not None
        
    def print_status(self):
        """Print current configuration status."""
        config = self.load_config()
        
        print("\n" + "=" * 60)
        print("  SPOTLESS - Configuration Status")
        print("=" * 60)
        print(f"  Machine ID:     {config.machine_id}")
        print(f"  Machine Name:   {config.machine_name}")
        print(f"  Location:       {config.location}")
        print(f"  Config Source:  {self._config_source.value.upper()}")
        print(f"  Database:       {'CONNECTED' if self.is_online else 'OFFLINE'}")
        print(f"  Last Updated:   {config.updated_at}")
        print("-" * 60)
        print("  Bath Sessions:")
        for session_type, session_config in config.session_configs.items():
            print(f"    - {session_type}: {session_config.description}")
        print("-" * 60)
        print("  Utility Sessions:")
        for session_type, utility_config in config.utility_configs.items():
            dur = f" ({utility_config.duration}s)" if utility_config.duration > 0 else ""
            print(f"    - {session_type}: {utility_config.description}{dur}")
        print("=" * 60 + "\n")
        
    def print_session_config(self, session_type: str):
        """Print configuration for a specific session type (full bath or utility)."""
        # Check if it's a utility session
        utility_config = self.get_utility_config(session_type)
        if utility_config:
            self.print_utility_config(session_type)
            return
            
        session_config = self.get_session_config(session_type)
        
        if not session_config:
            print(f"Unknown session type: {session_type}")
            return
            
        print("\n" + "-" * 50)
        print(f"  Session: {session_type}")
        print(f"  Description: {session_config.description}")
        print(f"  Handler: {session_config.handler}")
        print("-" * 50)
        print(f"  Shampoo (sval):       {session_config.sval} seconds")
        print(f"  Conditioner (cval):   {session_config.cval} seconds")
        print(f"  Disinfectant (dval):  {session_config.dval} seconds")
        print(f"  Water (wval):         {session_config.wval} seconds")
        print(f"  Dryer (dryval):       {session_config.dryval} seconds")
        print(f"  Flush (fval):         {session_config.fval} seconds")
        print(f"  Wait Time (wt):       {session_config.wt} seconds")
        print(f"  Stage Value (stval):  {session_config.stval} seconds")
        print(f"  Massage (msgval):     {session_config.msgval} seconds")
        print(f"  Towel Dry (tdry):     {session_config.tdry} seconds")
        print(f"  Process Type (pr):    {session_config.pr}")
        print(f"  Cond. Type (ctype):   {session_config.ctype}")
        print(f"  Start Stage:          {session_config.stage}")
        print("-" * 50 + "\n")
        
    def print_utility_config(self, session_type: str):
        """Print configuration for a utility session type."""
        utility_config = self.get_utility_config(session_type)
        
        if not utility_config:
            print(f"Unknown utility type: {session_type}")
            return
            
        print("\n" + "-" * 50)
        print(f"  Utility: {session_type}")
        print(f"  Description: {utility_config.description}")
        print("-" * 50)
        print(f"  Handler:      {utility_config.handler}")
        print(f"  Duration:     {utility_config.duration} seconds" if utility_config.duration > 0 else "  Duration:     N/A")
        print(f"  Needs QR:     {'Yes' if utility_config.needs_qr else 'No'}")
        print("-" * 50 + "\n")


# =============================================================================
# Global Instance
# =============================================================================
_config_manager: Optional[ConfigManager] = None

def get_config_manager() -> ConfigManager:
    """Get or create the global ConfigManager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


# =============================================================================
# Convenience Functions
# =============================================================================
def get_machine_id() -> Optional[str]:
    """Get the current machine ID."""
    return get_config_manager().get_machine_id()

def get_session_params(session_type: str) -> Optional[Dict]:
    """Get parameters for a session type."""
    return get_config_manager().get_session_params(session_type)

def list_session_types() -> List[str]:
    """List available session types."""
    return get_config_manager().list_session_types()


# =============================================================================
# Main - Test/Setup when run directly
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "=" * 60)
    print("  SPOTLESS - Configuration Manager Setup")
    print("=" * 60)
    
    mgr = ConfigManager()
    
    # Get machine ID (will prompt if not configured)
    machine_id = mgr.get_machine_id()
    
    if machine_id:
        # Load configuration
        config = mgr.load_config()
        
        # Print status
        mgr.print_status()
        
        # Print a sample session config
        print("\nSample Session Configuration:")
        mgr.print_session_config("small")
        
        print("\nConfiguration setup complete!")
        print(f"Config file: {CONFIG_FILE}")
        print(f"Machine ID file: {MACHINE_ID_FILE}")
    else:
        print("\nSetup cancelled.")
