"""
=============================================================================
Manual Module Control - Project Spotless
=============================================================================
Operator "module test" support: latch individual functional modules ON/OFF
with NO timing. Whatever is turned on stays on until the operator turns it
off (or hits "All off"). Lets the operator watch how each fluid line / motor
behaves in isolation, and see exactly which relays are currently energised.

This is intentionally SEPARATE from StageExecutor / SessionRunner, which run
timed, anti-fraud stage sequences. Here there is no clock — a module maps to
a fixed set of devices that we simply hold ON.

A "module" is a named group of device tokens:
    - bare token (e.g. "p1", "s8", "pump")  -> MQTT device via DeviceController
    - "gpio:<name>" (e.g. "gpio:dry")        -> Raspberry Pi GPIO relay

Device groups mirror the real session lines in session_stages.py so that what
the operator sees here matches what a real bath does:
    SHAMPOO_LINE_DEVICES   = s8, s1, s2, s4, d1, pump   (+ p1 shampoo dosing)
    DISINFECT_LINE_DEVICES = s8, s3, s4, s2, d2, pump   (+ p4 disinfect dosing)
    WATER_LINE_DEVICES     = s8, s5, s2, s4, pump
    flush_top / flush_bottom = flushmain, pump, gpio:top|bottom
    priming (fill)         = s8, s1, ro1                (priming_shampoo fill)
    empty tank             = d1, ro2, d2, ro4           (legacy Empty_tank/drain)

Reference counting: modules share devices (shampoo + conditioner both use the
common bath line). Turning one module off must NOT cut a relay another active
module still needs. We track the *desired* set as the union of all active
modules' devices and reconcile against what is currently energised.
=============================================================================
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# Module definitions
# =============================================================================
# Ordered list drives the on-screen layout. Keep keys URL/JSON safe (snake_case).

MANUAL_MODULES: Dict[str, Dict[str, Any]] = {
    "shampoo": {
        "label": "Shampoo",
        "hint": "Shampoo line open + shampoo dosing pump (p1).",
        # SHAMPOO_LINE_DEVICES + p1 (shampoo peristaltic dosing pump)
        "devices": ["s8", "s1", "s2", "s4", "d1", "pump", "p1"],
    },
    "conditioner": {
        "label": "Conditioner",
        "hint": "Same bath line as shampoo + conditioner dosing pump (p2).",
        # SHAMPOO_LINE_DEVICES + p2 (conditioner peristaltic dosing pump)
        "devices": ["s8", "s1", "s2", "s4", "d1", "pump", "p2"],
    },
    "disinfectant": {
        "label": "Disinfectant",
        "hint": "Disinfectant line open + disinfectant dosing pump (p4).",
        # DISINFECT_LINE_DEVICES + p4 (disinfectant peristaltic dosing pump)
        "devices": ["s8", "s3", "s4", "s2", "d2", "pump", "p4"],
    },
    "water": {
        "label": "Water",
        "hint": "Plain water rinse line (no dosing pump).",
        # WATER_LINE_DEVICES
        "devices": ["s8", "s5", "s2", "s4", "pump"],
    },
    "dryer": {
        "label": "Dryer",
        "hint": "Dryer relay (Pi GPIO 14).",
        "devices": ["gpio:dry"],
    },
    "cleanup_top": {
        "label": "Cleanup Top",
        "hint": "Top flush nozzle opened (bottom stays closed).",
        # flush_top line: autoflush gate + booster + top nozzle (Pi GPIO 20)
        "devices": ["flushmain", "pump", "gpio:top"],
    },
    "cleanup_bottom": {
        "label": "Cleanup Bottom",
        "hint": "Bottom flush nozzle opened (top stays closed).",
        # flush_bottom line: autoflush gate + booster + bottom nozzle (Pi GPIO 21)
        "devices": ["flushmain", "pump", "gpio:bottom"],
    },
    "priming": {
        "label": "Priming",
        "hint": "Fill the shampoo container line (s8, s1, ro1).",
        # priming_shampoo fill phase (legacy priming() fill leg)
        "devices": ["s8", "s1", "ro1"],
    },
    "empty_tank": {
        "label": "Empty Tank",
        "hint": "Drain both internal containers (legacy Empty_tank / drain).",
        # legacy Empty_tank (d1, ro2) extended to drain both containers
        "devices": ["d1", "ro2", "d2", "ro4"],
    },
}

MODULE_ORDER: List[str] = list(MANUAL_MODULES.keys())


# =============================================================================
# Friendly labels for the on-screen "currently ON" panel
# =============================================================================

def _token_label(token: str, dm, gpio_cfg: Dict[str, Any]) -> str:
    """Human-friendly label for a device token (best-effort)."""
    if token.startswith("gpio:"):
        name = token[5:]
        cfg = gpio_cfg.get(name, {}) if isinstance(gpio_cfg, dict) else {}
        return cfg.get("description", name)
    info = dm.get(token) if dm else None
    return info.description if info else token


def build_module_plan() -> List[Dict[str, Any]]:
    """Return the ordered modules with friendly device labels for the UI.

    Best-effort: if device_map / config can't be imported the raw token is
    used as the label so the page still renders.
    """
    try:
        from device_map import devices as _dm
    except Exception:
        _dm = None
    try:
        from config import GPIO_RELAYS as _gpio_cfg
    except Exception:
        _gpio_cfg = {}

    plan: List[Dict[str, Any]] = []
    for key in MODULE_ORDER:
        spec = MANUAL_MODULES[key]
        devices = [
            {"token": tok, "label": _token_label(tok, _dm, _gpio_cfg)}
            for tok in spec["devices"]
        ]
        plan.append({
            "key": key,
            "label": spec["label"],
            "hint": spec.get("hint", ""),
            "devices": devices,
        })
    return plan


def token_label(token: str) -> str:
    """Standalone friendly label for a single token (used by the API)."""
    try:
        from device_map import devices as _dm
    except Exception:
        _dm = None
    try:
        from config import GPIO_RELAYS as _gpio_cfg
    except Exception:
        _gpio_cfg = {}
    return _token_label(token, _dm, _gpio_cfg)


# =============================================================================
# Manual controller
# =============================================================================

class ManualController:
    """Latch modules ON/OFF with reference-counted device reconciliation.

    Construct with the live DeviceController (MQTT) and GPIOController. All
    public methods are thread-safe and return the full state dict so callers
    (HTTP routes) can hand the UI an authoritative snapshot every time.
    """

    def __init__(self, devices, gpio):
        self._devices = devices   # DeviceController (MQTT) or None
        self._gpio = gpio         # GPIOController or None
        self._lock = threading.RLock()
        self._active: Set[str] = set()      # active module keys
        self._energized: Set[str] = set()   # device tokens currently held ON

    # ---------------------------------------------------------------- internals
    def _set_token(self, token: str, state: bool) -> bool:
        """Drive one device token. Returns True on a successful hardware write."""
        try:
            if token.startswith("gpio:"):
                name = token[5:]
                relay = self._gpio.get_relay(name) if self._gpio else None
                if relay is None:
                    logger.warning(f"manual: unknown GPIO device {name!r}")
                    return False
                return bool(relay.set(state))
            handle = self._devices.get(token) if self._devices else None
            if handle is None:
                logger.warning(f"manual: unknown MQTT device {token!r}")
                return False
            return bool(handle.set(state))
        except Exception as e:
            logger.error(f"manual: error setting {token} -> {state}: {e}")
            return False

    def _desired_tokens(self) -> Set[str]:
        want: Set[str] = set()
        for key in self._active:
            want.update(MANUAL_MODULES[key]["devices"])
        return want

    def _reconcile(self) -> None:
        """Make the energised set match the union of active modules' devices."""
        want = self._desired_tokens()
        # Turn ON anything newly required.
        for token in want - self._energized:
            if self._set_token(token, True):
                self._energized.add(token)
        # Turn OFF anything no longer required by any active module.
        for token in list(self._energized - want):
            if self._set_token(token, False):
                self._energized.discard(token)

    # ---------------------------------------------------------------- public API
    def set_module(self, key: str, on: bool) -> Dict[str, Any]:
        if key not in MANUAL_MODULES:
            raise KeyError(key)
        with self._lock:
            if on:
                self._active.add(key)
                logger.info(f"manual: module ON  -> {key}")
            else:
                self._active.discard(key)
                logger.info(f"manual: module OFF -> {key}")
            self._reconcile()
            return self._state_locked()

    def all_off(self) -> Dict[str, Any]:
        with self._lock:
            logger.warning("manual: ALL OFF (operator)")
            self._active.clear()
            for token in list(self._energized):
                self._set_token(token, False)
            self._energized.clear()
            return self._state_locked()

    @property
    def any_active(self) -> bool:
        with self._lock:
            return bool(self._active)

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> Dict[str, Any]:
        return {
            "modules": {k: (k in self._active) for k in MODULE_ORDER},
            "energized": sorted(self._energized),
            "any_active": bool(self._active),
        }
