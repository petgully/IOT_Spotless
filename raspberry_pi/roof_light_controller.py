"""
=============================================================================
Roof Light Controller - Project Spotless
=============================================================================
Controls the roof tubelight with OR-logic:

    Light ON when EITHER:
        1. A session is active (QR validated → session complete)
        2. Current time falls within the configurable evening window

If the evening schedule turns the light on at 7 PM and a session starts at
8:30 PM and finishes at 9:15 PM, the light stays on the whole time —
the schedule started it, then the session keeps it on past 9 PM.

Config (from config.json → "roof_light"):
    evening_on_time   — "HH:MM" (default "19:00")
    evening_off_time  — "HH:MM" (default "21:00")

A background thread checks every 60 seconds to handle scheduled on/off.
=============================================================================
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_ROOF_CONFIG = {
    "evening_on_time": "19:00",
    "evening_off_time": "21:00",
}


class RoofLightController:
    """
    Roof tubelight controller with session + evening schedule OR-logic.

    Usage:
        rc = RoofLightController(gpio_controller, config_dict)
        rc.start()                  # starts the background scheduler
        rc.on_session_start()       # QR validated, session beginning
        rc.on_session_complete()    # session finished
        rc.stop()                   # cleanup
    """

    def __init__(self, gpio, config: Optional[Dict] = None):
        """
        Args:
            gpio:   GPIOController instance (must have .roof relay)
            config: dict with evening_on_time, evening_off_time
        """
        self.gpio = gpio
        cfg = config or DEFAULT_ROOF_CONFIG
        self.evening_on = cfg.get("evening_on_time", "19:00")
        self.evening_off = cfg.get("evening_off_time", "21:00")

        self._session_active = False
        self._current_state = False
        self._stop_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None

    # =========================================================================
    # Public API
    # =========================================================================

    def start(self):
        """Start the background scheduler."""
        logger.info(f"Roof light controller starting — evening window "
                    f"{self.evening_on} – {self.evening_off}")
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self.update()

    def stop(self):
        """Stop the scheduler and turn off the light."""
        self._stop_event.set()
        self._set_light(False)
        logger.info("Roof light controller stopped")

    def on_session_start(self):
        """Called when a session begins (QR validated)."""
        self._session_active = True
        self.update()

    def on_session_complete(self):
        """Called when a session finishes (or is stopped/errors out)."""
        self._session_active = False
        self.update()

    def update(self):
        """Recalculate whether the light should be on or off."""
        should_be_on = self._session_active or self._is_evening_window()
        if should_be_on != self._current_state:
            action = "ON" if should_be_on else "OFF"
            reason_parts = []
            if self._session_active:
                reason_parts.append("session active")
            if self._is_evening_window():
                reason_parts.append("evening schedule")
            reason = ", ".join(reason_parts) if reason_parts else "no trigger"
            logger.info(f"Roof light {action} — {reason}")
        self._set_light(should_be_on)
        self._current_state = should_be_on

    def apply_config(self, config: Dict):
        """Hot-reload window times without restarting the controller.

        Used by the admin UI; calls update() so any change takes effect
        immediately (light flips on/off if the new window now applies).
        """
        if config is None:
            return
        new_on  = config.get("evening_on_time",  self.evening_on)
        new_off = config.get("evening_off_time", self.evening_off)
        if new_on != self.evening_on or new_off != self.evening_off:
            logger.info(
                f"Roof light config reload: window "
                f"{self.evening_on}-{self.evening_off} -> {new_on}-{new_off}"
            )
        self.evening_on = new_on
        self.evening_off = new_off
        self.update()

    @property
    def is_on(self) -> bool:
        return self._current_state

    # =========================================================================
    # Internal
    # =========================================================================

    def _set_light(self, state: bool):
        try:
            relay = self.gpio.roof
            if relay:
                relay.set(state)
        except Exception as e:
            logger.error(f"Failed to set roof light relay: {e}")

    def _is_evening_window(self) -> bool:
        """Check if current time is within the evening on/off window."""
        now = datetime.now()
        try:
            on_parts = self.evening_on.split(":")
            off_parts = self.evening_off.split(":")
            on_hour, on_min = int(on_parts[0]), int(on_parts[1])
            off_hour, off_min = int(off_parts[0]), int(off_parts[1])
        except (ValueError, IndexError):
            return False

        on_minutes = on_hour * 60 + on_min
        off_minutes = off_hour * 60 + off_min
        now_minutes = now.hour * 60 + now.minute

        if on_minutes <= off_minutes:
            return on_minutes <= now_minutes < off_minutes
        else:
            # Wraps past midnight (e.g., 22:00 – 06:00)
            return now_minutes >= on_minutes or now_minutes < off_minutes

    def _scheduler_loop(self):
        """Background loop — checks every 60 seconds for schedule changes."""
        logger.info("Roof light scheduler thread started")
        while not self._stop_event.is_set():
            self.update()
            self._stop_event.wait(60)
