"""
=============================================================================
Configuration Manager - Project Spotless
=============================================================================
Manages machine configuration with offline support.

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
CONFIG_DIR = Path.home() / ".spotless"
CONFIG_FILE = CONFIG_DIR / "config.json"
MACHINE_ID_FILE = CONFIG_DIR / "machine_id.txt"
SESSIONS_DIR = CONFIG_DIR / "sessions"
CACHE_FILE = CONFIG_DIR / "db_cache.json"


class ConfigSource(Enum):
    LOCAL = "local"
    DATABASE = "database"
    DEFAULT = "default"


# =============================================================================
# Default Configuration
# =============================================================================

DEFAULT_CONFIG = {
    "machine_id": "",
    "machine_name": "Spotless Booth",
    "location": "Not configured",
    "is_active": True,

    "geyser": {
        "morning_preheat_time": "07:00",
        "heat_duration_sec": 480,
        "safety_cutoff_sec": 1800,
    },

    "roof_light": {
        "evening_on_time": "19:00",
        "evening_off_time": "21:00",
    },

    "session_types": {
        "small": {
            "description": "Small Pet Bath Session",
            "sval": 80, "cval": 80, "dval": 60, "wval": 60,
            "dryval": 480, "fval": 60, "wt": 30, "msgval": 30,
            "tdry": 30, "pr": 20, "ctype": 100,
        },
        "large": {
            "description": "Large Pet Bath Session",
            "sval": 100, "cval": 100, "dval": 60, "wval": 60,
            "dryval": 600, "fval": 60, "wt": 50, "msgval": 30,
            "tdry": 30, "pr": 20, "ctype": 100,
        },
        "custdiy": {
            "description": "Customer DIY Session",
            "sval": 100, "cval": 100, "dval": 60, "wval": 60,
            "dryval": 600, "fval": 60, "wt": 12, "msgval": 30,
            "tdry": 30, "pr": 10, "ctype": 100,
        },
        "medsmall": {
            "description": "Medicated Bath — Small Pet",
            "sval": 80, "cval": 80, "dval": 60, "wval": 60,
            "dryval": 480, "fval": 60, "wt": 30, "msgval": 30,
            "tdry": 30, "pr": 20, "ctype": 200,
        },
        "medlarge": {
            "description": "Medicated Bath — Large Pet",
            "sval": 100, "cval": 100, "dval": 60, "wval": 60,
            "dryval": 600, "fval": 60, "wt": 50, "msgval": 30,
            "tdry": 30, "pr": 20, "ctype": 200,
        },
        "onlydisinfectant": {
            "description": "Disinfectant Only",
        },
        "quicktest": {"description": "Quick Relay Test"},
        "onlydrying": {"description": "Dryer Only (5 min)"},
        "onlywater": {"description": "Water Only (90s)"},
        "onlyflush": {"description": "Flush Only (60s)"},
        "onlyshampoo": {"description": "Shampoo Only"},
        "empty001": {"description": "Empty Tank (3 min)"},
        "demo": {"description": "Demo Mode — Sequential Relay Test"},
    },

    "created_at": "",
    "updated_at": "",
}


# =============================================================================
# Configuration Manager
# =============================================================================
class ConfigManager:
    """
    Manages machine configuration with offline support.
    
    Usage:
        config_mgr = ConfigManager()
        machine_id = config_mgr.get_machine_id()
        config = config_mgr.load_config()
        params = config_mgr.get_session_params("small")
        stages = config_mgr.get_session_stages("small")
    """
    
    def __init__(self):
        self._machine_id: Optional[str] = None
        self._config: Optional[Dict] = None
        self._config_source: ConfigSource = ConfigSource.DEFAULT
        self._db_manager = None
        self._ensure_directories()
        
    def _ensure_directories(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        
    # =========================================================================
    # Machine ID Management
    # =========================================================================
    
    def get_machine_id(self, prompt_if_missing: bool = True) -> Optional[str]:
        if self._machine_id:
            return self._machine_id
            
        if MACHINE_ID_FILE.exists():
            try:
                self._machine_id = MACHINE_ID_FILE.read_text().strip()
                if self._machine_id:
                    logger.info(f"Loaded machine ID: {self._machine_id}")
                    return self._machine_id
            except Exception as e:
                logger.warning(f"Error reading machine ID file: {e}")
                
        if prompt_if_missing:
            self._machine_id = self._prompt_machine_id()
            if self._machine_id:
                self.save_machine_id(self._machine_id)
                
        return self._machine_id
        
    def _prompt_machine_id(self) -> Optional[str]:
        print("\n" + "=" * 50)
        print("  SPOTLESS — Machine Configuration")
        print("=" * 50)
        print("\nNo machine ID configured.")
        print("Please enter the Machine ID for this booth.")
        print("(e.g., BS01, BS02, HONER01)\n")
        
        while True:
            machine_id = input("Machine ID: ").strip().upper()
            if not machine_id or len(machine_id) < 2:
                print("Machine ID must be at least 2 characters.")
                continue
            confirm = input(f"Confirm Machine ID '{machine_id}'? (y/n): ").strip().lower()
            if confirm == 'y':
                return machine_id
            print("Let's try again.\n")
            
    def save_machine_id(self, machine_id: str):
        try:
            MACHINE_ID_FILE.write_text(machine_id)
            self._machine_id = machine_id
            logger.info(f"Saved machine ID: {machine_id}")
        except Exception as e:
            logger.error(f"Error saving machine ID: {e}")
            
    def clear_machine_id(self):
        try:
            if MACHINE_ID_FILE.exists():
                MACHINE_ID_FILE.unlink()
            self._machine_id = None
        except Exception as e:
            logger.error(f"Error clearing machine ID: {e}")
            
    # =========================================================================
    # Configuration Loading
    # =========================================================================
    
    def load_config(self, force_reload: bool = False) -> Dict:
        if self._config and not force_reload:
            return self._config
            
        machine_id = self.get_machine_id()
        if not machine_id:
            raise ValueError("Machine ID not configured")

        # Try local config file
        local_config = self._load_from_local(machine_id)
        if local_config:
            self._config = local_config
            self._config_source = ConfigSource.LOCAL
            logger.info(f"Loaded config from LOCAL for {machine_id}")
            return self._config
            
        # Use defaults
        self._config = _create_default_config(machine_id)
        self._config_source = ConfigSource.DEFAULT
        self._save_to_local(self._config)
        logger.info(f"Using DEFAULT config for {machine_id}")
        return self._config
        
    def _load_from_local(self, machine_id: str) -> Optional[Dict]:
        if not CONFIG_FILE.exists():
            return None
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            if data.get('machine_id') == machine_id:
                data = _merge_defaults(data)
                return data
            else:
                logger.warning(f"Local config is for different machine: {data.get('machine_id')}")
                return None
        except Exception as e:
            logger.error(f"Error loading local config: {e}")
            return None
            
    def _save_to_local(self, config: Dict):
        try:
            config["updated_at"] = datetime.now().isoformat()
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved config to {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error saving local config: {e}")
            
    # =========================================================================
    # Session Configuration Access
    # =========================================================================
    
    def get_session_params(self, session_type: str) -> Optional[Dict]:
        """Get timing parameters for a session type (sval, cval, etc.)."""
        config = self.load_config()
        st_config = config.get("session_types", {}).get(session_type)
        if st_config:
            params = {k: v for k, v in st_config.items() if k != "description"}
            return params
        return None

    def get_session_stages(self, session_type: str) -> list:
        """
        Build the stage list for a session type.

        Uses timing params from config to build stages via session_stages module.
        This is the main entry point — call this to get the full list of stages
        with device patterns, durations, and UI info.
        """
        from session_stages import (
            get_stages, _full_bath_stages, SESSION_STAGES,
        )

        params = self.get_session_params(session_type)

        full_bath_types = {"small", "large", "custdiy", "medsmall", "medlarge"}
        if session_type in full_bath_types and params:
            return _full_bath_stages(
                sval=params.get("sval", 80),
                cval=params.get("cval", 80),
                dval=params.get("dval", 60),
                wval=params.get("wval", 60),
                dryval=params.get("dryval", 480),
                fval=params.get("fval", 60),
                wt=params.get("wt", 30),
                msgval=params.get("msgval", 30),
                tdry=params.get("tdry", 30),
                pr=params.get("pr", 20),
                ctype=params.get("ctype", 100),
            )

        return get_stages(session_type)

    def get_session_description(self, session_type: str) -> str:
        config = self.load_config()
        st_config = config.get("session_types", {}).get(session_type, {})
        return st_config.get("description", "Unknown")

    def list_session_types(self) -> List[str]:
        config = self.load_config()
        return list(config.get("session_types", {}).keys())

    def list_bath_session_types(self) -> List[str]:
        """List only the full-bath session types (not utility)."""
        return [t for t in self.list_session_types()
                if t in {"small", "large", "custdiy", "medsmall", "medlarge"}]

    def list_utility_types(self) -> List[str]:
        bath = set(self.list_bath_session_types())
        return [t for t in self.list_session_types() if t not in bath]

    # =========================================================================
    # Peripheral Config Access
    # =========================================================================

    def get_geyser_config(self) -> Dict:
        config = self.load_config()
        return config.get("geyser", DEFAULT_CONFIG["geyser"])

    def get_roof_light_config(self) -> Dict:
        config = self.load_config()
        return config.get("roof_light", DEFAULT_CONFIG["roof_light"])

    # =========================================================================
    # Configuration Updates
    # =========================================================================
    
    def update_session_param(self, session_type: str, key: str, value):
        config = self.load_config()
        st = config.get("session_types", {}).get(session_type)
        if st is None:
            logger.error(f"Unknown session type: {session_type}")
            return False
        st[key] = value
        logger.info(f"Updated {session_type}.{key} = {value}")
        self._save_to_local(config)
        return True

    def update_geyser_config(self, **kwargs):
        config = self.load_config()
        g = config.setdefault("geyser", {})
        for k, v in kwargs.items():
            g[k] = v
        self._save_to_local(config)

    def update_roof_light_config(self, **kwargs):
        config = self.load_config()
        r = config.setdefault("roof_light", {})
        for k, v in kwargs.items():
            r[k] = v
        self._save_to_local(config)

    def update_machine_info(self, **kwargs):
        config = self.load_config()
        for k, v in kwargs.items():
            if k not in ("session_types", "geyser", "roof_light"):
                config[k] = v
        self._save_to_local(config)
        
    # =========================================================================
    # Session Logging (Offline)
    # =========================================================================
    
    def log_session(self, session_type: str, qr_code: str, 
                    start_time: datetime, end_time: datetime,
                    status: str = "completed") -> str:
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
        self._db_manager = db_manager
        logger.info("Database manager connected")
        
    def sync_to_database(self) -> bool:
        if not self._db_manager:
            logger.warning("Database manager not configured")
            return False
        # TODO: Implement database sync
        return True
        
    # =========================================================================
    # Status
    # =========================================================================
    
    @property
    def config_source(self) -> ConfigSource:
        return self._config_source
        
    @property
    def is_online(self) -> bool:
        return self._db_manager is not None

    def print_status(self):
        config = self.load_config()
        print("\n" + "=" * 60)
        print("  SPOTLESS — Configuration Status")
        print("=" * 60)
        print(f"  Machine ID:    {config.get('machine_id')}")
        print(f"  Machine Name:  {config.get('machine_name')}")
        print(f"  Location:      {config.get('location')}")
        print(f"  Config Source:  {self._config_source.value.upper()}")
        print(f"  Database:      {'CONNECTED' if self.is_online else 'OFFLINE'}")
        print("-" * 60)
        print("  Session Types:")
        for st, cfg in config.get("session_types", {}).items():
            desc = cfg.get("description", "")
            print(f"    {st:20} — {desc}")
        print("-" * 60)
        g = config.get("geyser", {})
        print(f"  Geyser preheat: {g.get('morning_preheat_time', '?')}, "
              f"safety: {g.get('safety_cutoff_sec', '?')}s")
        r = config.get("roof_light", {})
        print(f"  Roof light:     {r.get('evening_on_time', '?')} – "
              f"{r.get('evening_off_time', '?')}")
        print("=" * 60 + "\n")


# =============================================================================
# Helpers
# =============================================================================

def _create_default_config(machine_id: str) -> Dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["machine_id"] = machine_id
    config["machine_name"] = f"Spotless Booth {machine_id}"
    now = datetime.now().isoformat()
    config["created_at"] = now
    config["updated_at"] = now
    return config


def _merge_defaults(config: Dict) -> Dict:
    """Merge any new default keys into an existing config."""
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            logger.info(f"Added new config key: {key}")
        elif isinstance(value, dict) and isinstance(config.get(key), dict):
            for sub_key, sub_val in value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = sub_val
                    logger.info(f"Added new config key: {key}.{sub_key}")
    return config


# =============================================================================
# Global Instance
# =============================================================================
_config_manager: Optional[ConfigManager] = None

def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_machine_id() -> Optional[str]:
    return get_config_manager().get_machine_id()

def get_session_params(session_type: str) -> Optional[Dict]:
    return get_config_manager().get_session_params(session_type)

def list_session_types() -> List[str]:
    return get_config_manager().list_session_types()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mgr = ConfigManager()
    machine_id = mgr.get_machine_id()
    if machine_id:
        mgr.load_config()
        mgr.print_status()
        print(f"\nConfig file: {CONFIG_FILE}")
