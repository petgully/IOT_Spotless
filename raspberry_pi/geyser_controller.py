"""
=============================================================================
Geyser Controller - Project Spotless
=============================================================================
Smart water heater management to keep warm water ready without running 24/7.

Strategies:
    1. Morning pre-heat — Turn on geyser at a configurable time (default 07:00)
       so warm water is ready for the first session of the day.
    2. Post-session re-heat — After every session completes, re-heat the water
       for the next customer.  The hot water stays in the geyser tank between
       sessions.
    3. Safety cutoff — If the geyser has been on for more than 30 minutes
       continuously (configurable), force it off to prevent overheating.

Config (from config.json → "geyser"):
    morning_preheat_time  — "HH:MM" string (default "07:00")
    heat_duration_sec     — seconds to heat per cycle (default 480 = 8 min)
    safety_cutoff_sec     — max continuous ON time (default 1800 = 30 min)
=============================================================================
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_GEYSER_CONFIG = {
    "morning_preheat_time": "07:00",
    "heat_duration_sec": 480,
    "safety_cutoff_sec": 1800,
}


class GeyserController:
    """
    Smart geyser controller with morning pre-heat, post-session re-heat,
    and safety cutoff.

    Usage:
        gc = GeyserController(gpio_controller, config_dict)
        gc.start()                  # starts the background scheduler
        gc.on_session_complete()    # called by SessionRunner after each session
        gc.stop()                   # cleanup
    """

    def __init__(self, gpio, config: Optional[Dict] = None):
        """
        Args:
            gpio:   GPIOController instance (must have .geyser relay)
            config: dict with morning_preheat_time, heat_duration_sec,
                    safety_cutoff_sec
        """
        self.gpio = gpio
        cfg = config or DEFAULT_GEYSER_CONFIG
        self.morning_time = cfg.get("morning_preheat_time", "07:00")
        self.heat_duration = cfg.get("heat_duration_sec", 480)
        self.safety_cutoff = cfg.get("safety_cutoff_sec", 1800)

        self._heating = False
        self._heat_start: Optional[datetime] = None
        self._stop_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._heat_timer: Optional[threading.Timer] = None
        self._safety_timer: Optional[threading.Timer] = None
        self._morning_fired_today = False

    # =========================================================================
    # Public API
    # =========================================================================

    def start(self):
        """Start the background scheduler thread."""
        logger.info(f"Geyser controller starting — morning preheat at "
                    f"{self.morning_time}, heat={self.heat_duration}s, "
                    f"safety={self.safety_cutoff}s")
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def stop(self):
        """Stop everything and turn geyser off."""
        self._stop_event.set()
        self._cancel_timers()
        self._set_geyser(False)
        logger.info("Geyser controller stopped")

    def start_heating(self):
        """Turn on the geyser and schedule auto-off after heat_duration."""
        if self._heating:
            logger.debug("Geyser already heating — ignoring start_heating()")
            return
        logger.info(f"Geyser ON — heating for {self.heat_duration}s")
        self._set_geyser(True)
        self._heating = True
        self._heat_start = datetime.now()

        self._cancel_timers()

        self._heat_timer = threading.Timer(self.heat_duration, self._auto_off)
        self._heat_timer.daemon = True
        self._heat_timer.start()

        self._safety_timer = threading.Timer(self.safety_cutoff, self._safety_off)
        self._safety_timer.daemon = True
        self._safety_timer.start()

    def on_session_complete(self):
        """Called by SessionRunner after each session completes."""
        logger.info("Post-session geyser re-heat triggered")
        self._heating = False
        self._cancel_timers()
        self.start_heating()

    @property
    def is_heating(self) -> bool:
        return self._heating

    # =========================================================================
    # Internal
    # =========================================================================

    def _set_geyser(self, state: bool):
        try:
            relay = self.gpio.geyser
            if relay:
                relay.set(state)
        except Exception as e:
            logger.error(f"Failed to set geyser relay: {e}")

    def _auto_off(self):
        """Called after heat_duration — normal shutoff."""
        if self._heating:
            logger.info("Geyser OFF — heating cycle complete")
            self._set_geyser(False)
            self._heating = False

    def _safety_off(self):
        """Called after safety_cutoff — forced shutoff."""
        if self._heating:
            elapsed = (datetime.now() - self._heat_start).total_seconds() if self._heat_start else 0
            logger.warning(f"SAFETY CUTOFF — geyser forced OFF after {int(elapsed)}s")
            self._set_geyser(False)
            self._heating = False

    def _cancel_timers(self):
        if self._heat_timer:
            self._heat_timer.cancel()
            self._heat_timer = None
        if self._safety_timer:
            self._safety_timer.cancel()
            self._safety_timer = None

    def _scheduler_loop(self):
        """Background loop — checks once per minute for morning preheat."""
        logger.info("Geyser scheduler thread started")
        while not self._stop_event.is_set():
            now = datetime.now()

            if self._should_morning_preheat(now):
                logger.info(f"Morning pre-heat triggered at {now.strftime('%H:%M')}")
                self._morning_fired_today = True
                self.start_heating()

            if now.hour == 0 and now.minute == 0:
                self._morning_fired_today = False

            self._stop_event.wait(60)

    def _should_morning_preheat(self, now: datetime) -> bool:
        if self._morning_fired_today:
            return False
        try:
            parts = self.morning_time.split(":")
            target_hour = int(parts[0])
            target_minute = int(parts[1])
        except (ValueError, IndexError):
            return False

        return now.hour == target_hour and now.minute == target_minute
