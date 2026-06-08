"""
=============================================================================
Configuration Manager - Project Spotless (Contract v1.1)
=============================================================================
Manages machine configuration with offline support. The kiosk's runtime
state lives under ~/.spotless/ on the Pi:

    ~/.spotless/config.json      - Main configuration (size_profiles, peripherals)
    ~/.spotless/machine_id.txt   - Cached machine ID
    ~/.spotless/sessions/        - Legacy session JSON logs (offline)
    ~/.spotless/db_cache.json    - Reserved for future cloud snapshot cache

Per contract section 6, the SET A / SET B timing values live in the
`size_profiles` block of config.json and override the defaults baked into
session_stages.py. Per-booking timing overrides have been REMOVED — the
kiosk derives all timings from (size, package, addons).
=============================================================================
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Paths
# =============================================================================
CONFIG_DIR      = Path.home() / ".spotless"
CONFIG_FILE     = CONFIG_DIR / "config.json"
MACHINE_ID_FILE = CONFIG_DIR / "machine_id.txt"
SESSIONS_DIR    = CONFIG_DIR / "sessions"
CACHE_FILE      = CONFIG_DIR / "db_cache.json"


class ConfigSource(Enum):
    LOCAL = "local"
    DATABASE = "database"
    DEFAULT = "default"


# =============================================================================
# Default Configuration (contract v1.1 §6.1)
# =============================================================================
# size_profiles holds the SET A / SET B timing defaults. Edit this file or the
# JSON on disk to tune. Per-stage budgets are derived from these values inside
# session_stages.py.

DEFAULT_CONFIG: Dict[str, Any] = {
    "machine_id": "",
    "machine_name": "Spotless Booth",
    "location": "Not configured",
    "is_active": True,

    # --- Peripheral controllers ---
    "geyser": {
        "morning_preheat_time": "07:00",
        "heat_duration_sec": 480,
        "safety_cutoff_sec": 1800,
    },
    "roof_light": {
        "evening_on_time":  "19:00",
        "evening_off_time": "21:00",
    },

    # --- Size profiles (contract §6.1) ---
    "size_profiles": {
        "A": {
            "description": "SET A — small / medium / medium_large / large / indie",
            "sval":   80, "cval":   80, "wval":   60, "dval":   60,
            "dryval": 600, "fval":   60, "wt":     30,
            "msgval": 30,  "tdry":   30,
            "prime_fill": 30, "prime_empty": 6, "prime_empty_2": 12,
        },
        "B": {
            "description": "SET B — xl",
            "sval":  120, "cval":  120, "wval":   90, "dval":   60,
            "dryval": 800, "fval":   60, "wt":     60,
            "msgval": 30,  "tdry":   30,
            "prime_fill": 30, "prime_empty": 6, "prime_empty_2": 12,
        },
    },

    # --- Maintenance / temporary hardware workarounds ---
    "maintenance": {
        # Plan B shampoo: bypass the s1 shampoo-line gate (high reverse flow
        # while it's being repaired). When true, the regular (p1) shampoo
        # stage routes through s5 and pulses s2 instead of holding s1+s2 open.
        # Flip back to false once s1 is fixed. See session_stages.py.
        "shampoo_plan_b": False,
    },

    # --- Cloud sync settings (contract §8.7) ---
    "cloud_sync": {
        "enabled": True,
        "retry_seconds": 30,
        "queue_max_warn": 100,
    },

    # --- Resume / abandonment settings (contract §9) ---
    "resume": {
        "abandonment_days": 7,        # contract §9.3
        "resume_count_cap": 10,       # contract §9.4
        "session_max_age_days": 30,   # contract §9.4
    },

    "created_at": "",
    "updated_at": "",
}


# =============================================================================
# Configuration Manager
# =============================================================================
class ConfigManager:
    """Manages machine configuration with offline support.

    Usage:
        cfg = ConfigManager()
        machine_id  = cfg.get_machine_id()
        config_dict = cfg.load_config()
        profile     = cfg.get_size_profile("A")
        overrides   = cfg.get_size_profile_overrides()  # both A and B, for session_stages
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
            if confirm == "y":
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

        local_config = self._load_from_local(machine_id)
        if local_config:
            self._config = local_config
            self._config_source = ConfigSource.LOCAL
            logger.info(f"Loaded config from LOCAL for {machine_id}")
            return self._config

        self._config = _create_default_config(machine_id)
        self._config_source = ConfigSource.DEFAULT
        self._save_to_local(self._config)
        logger.info(f"Using DEFAULT config for {machine_id}")
        return self._config

    def _load_from_local(self, machine_id: str) -> Optional[Dict]:
        if not CONFIG_FILE.exists():
            return None
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            if data.get("machine_id") == machine_id:
                data = _merge_defaults(data)
                return data
            logger.warning(
                f"Local config is for different machine: {data.get('machine_id')}"
            )
            return None
        except Exception as e:
            logger.error(f"Error loading local config: {e}")
            return None

    def _save_to_local(self, config: Dict):
        """Atomic write: temp file + os.replace.

        Power loss mid-write can otherwise leave config.json half-written and
        unparseable, which would refuse to start the kiosk on next boot.

        Raises OSError (or subclass) on failure so callers — notably the
        admin UI — can surface a real error to the operator instead of
        silently flashing "saved" while the disk write blew up.
        """
        config["updated_at"] = datetime.now().isoformat()
        tmp_path = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, CONFIG_FILE)
            logger.info(f"Saved config to {CONFIG_FILE}")
        except Exception:
            logger.exception("Error saving local config")
            try:
                tmp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            raise

    def reload(self) -> Dict:
        """Force-reread config.json from disk. Returns the freshly loaded dict.

        Use after an out-of-band edit to config.json (admin UI, manual edit)
        so subsequent reads see the new values without restarting the service.
        """
        return self.load_config(force_reload=True)

    # =========================================================================
    # Size profile access (contract §6.1)
    # =========================================================================

    def get_size_profile(self, key: str) -> Dict[str, int]:
        """Get the timing dict for profile 'A' or 'B'."""
        config = self.load_config()
        profiles = config.get("size_profiles", DEFAULT_CONFIG["size_profiles"])
        profile = profiles.get(key.upper())
        if profile is None:
            logger.warning(f"Unknown size profile key {key!r}, using A")
            profile = profiles.get("A", DEFAULT_CONFIG["size_profiles"]["A"])
        # Strip 'description' before returning to caller
        return {k: v for k, v in profile.items() if k != "description"}

    def get_size_profile_overrides(self) -> Dict[str, Dict[str, int]]:
        """Return both A + B profiles as a dict for session_stages.build_session()."""
        return {
            "A": self.get_size_profile("A"),
            "B": self.get_size_profile("B"),
        }

    def update_size_profile(self, key: str, **kwargs) -> bool:
        """Patch one or more timing fields in profile A or B."""
        key = key.upper()
        config = self.load_config()
        profiles = config.setdefault("size_profiles", {})
        prof = profiles.setdefault(key, {})
        for k, v in kwargs.items():
            prof[k] = v
            logger.info(f"Updated size_profiles.{key}.{k} = {v}")
        self._save_to_local(config)
        return True

    # =========================================================================
    # Peripheral Config Access
    # =========================================================================

    def get_geyser_config(self) -> Dict:
        config = self.load_config()
        return config.get("geyser", DEFAULT_CONFIG["geyser"])

    def get_roof_light_config(self) -> Dict:
        config = self.load_config()
        return config.get("roof_light", DEFAULT_CONFIG["roof_light"])

    def get_cloud_sync_config(self) -> Dict:
        config = self.load_config()
        return config.get("cloud_sync", DEFAULT_CONFIG["cloud_sync"])

    def get_resume_config(self) -> Dict:
        config = self.load_config()
        return config.get("resume", DEFAULT_CONFIG["resume"])

    def get_maintenance_config(self) -> Dict:
        config = self.load_config()
        return config.get("maintenance", DEFAULT_CONFIG["maintenance"])

    def get_shampoo_plan_b(self) -> bool:
        """Temporary flag: route the regular shampoo stage through Plan B
        (s1 bypassed, s5 opened, s2 pulsed) while s1 is being repaired."""
        return bool(self.get_maintenance_config().get("shampoo_plan_b", False))

    # =========================================================================
    # Configuration Updates
    # =========================================================================

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
        reserved = {"size_profiles", "geyser", "roof_light", "cloud_sync",
                    "resume", "maintenance"}
        for k, v in kwargs.items():
            if k not in reserved:
                config[k] = v
        self._save_to_local(config)

    # =========================================================================
    # Session Logging (Offline, legacy JSON)
    # =========================================================================
    # NOTE: These are local-only forensic logs. The authoritative session state
    # lives in (a) data/session_state.db (local SQLite) and (b) booking_sessions
    # cloud table. See session_progress.py for the new mechanism.

    def log_session(self, session_type: str, qr_code: str,
                    start_time: datetime, end_time: datetime,
                    status: str = "completed") -> str:
        duration = (end_time - start_time).total_seconds()
        log_data = {
            "machine_id": self._machine_id,
            "session_type": session_type,
            "qr_code": qr_code,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": int(duration),
            "status": status,
            "synced_to_db": False,
        }
        filename = f"{start_time.strftime('%Y%m%d_%H%M%S')}_{session_type}.json"
        filepath = SESSIONS_DIR / filename
        try:
            with open(filepath, "w") as f:
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
                with open(filepath, "r") as f:
                    data = json.load(f)
                if not data.get("synced_to_db", False):
                    data["_filepath"] = str(filepath)
                    pending.append(data)
            except Exception as e:
                logger.warning(f"Error reading session log {filepath}: {e}")
        return pending

    def mark_session_synced(self, filepath: str):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            data["synced_to_db"] = True
            data["synced_at"] = datetime.now().isoformat()
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error marking session synced: {e}")

    # =========================================================================
    # Database Manager Integration
    # =========================================================================

    def set_database_manager(self, db_manager):
        self._db_manager = db_manager
        logger.info("Database manager connected")

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
        print("  SPOTLESS — Configuration Status (v1.1)")
        print("=" * 60)
        print(f"  Machine ID:    {config.get('machine_id')}")
        print(f"  Machine Name:  {config.get('machine_name')}")
        print(f"  Location:      {config.get('location')}")
        print(f"  Config Source: {self._config_source.value.upper()}")
        print(f"  Database:      {'CONNECTED' if self.is_online else 'OFFLINE'}")
        print("-" * 60)
        print("  Size Profiles:")
        for key, prof in config.get("size_profiles", {}).items():
            print(f"    {key}: shampoo={prof.get('sval')}s, water={prof.get('wval')}s, "
                  f"dryer={prof.get('dryval')}s, pump={prof.get('wt')}s")
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
    """Merge any new default keys into an existing config (forward-compat)."""
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = json.loads(json.dumps(value))
            logger.info(f"Added new config key: {key}")
        elif isinstance(value, dict) and isinstance(config.get(key), dict):
            for sub_key, sub_val in value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = (
                        json.loads(json.dumps(sub_val))
                        if isinstance(sub_val, (dict, list))
                        else sub_val
                    )
                    logger.info(f"Added new config key: {key}.{sub_key}")
    # Drop deprecated `session_types` block from older configs (v1.0 -> v1.1).
    if "session_types" in config:
        logger.info("Migration: dropping deprecated `session_types` block "
                    "(replaced by `size_profiles` in v1.1)")
        config.pop("session_types", None)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mgr = ConfigManager()
    machine_id = mgr.get_machine_id()
    if machine_id:
        mgr.load_config()
        mgr.print_status()
        print(f"\nConfig file: {CONFIG_FILE}")
