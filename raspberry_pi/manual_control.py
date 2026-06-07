"""
=============================================================================
Manual Module Control - Project Spotless
=============================================================================
Operator "module test" support: exercise individual functional modules.

Two kinds of module:

  * LATCH modules (shampoo, conditioner, disinfectant, water, dryer, cleanup
    top/bottom, empty tank): turn ON and the relays stay on until the operator
    turns them off (or hits "All off"). No timer.

  * SEQUENCE modules (priming shampoo, priming disinfectant): turn ON and they
    run a fixed timed sequence (fill -> drain) then switch themselves off.
    Toggling them off mid-run aborts and drops their relays.

This is intentionally SEPARATE from StageExecutor / SessionRunner (the timed,
anti-fraud bath orchestrator). Here a module just maps to device tokens.

A device token is:
    - bare token (e.g. "p1", "s8", "pump")  -> MQTT device via DeviceController
    - "gpio:<name>" (e.g. "gpio:dry")        -> Raspberry Pi GPIO relay

Device groups mirror the real session lines in session_stages.py so what the
operator sees here matches a real bath. NOTE: s8, pump and flushmain are now
Pi-direct GPIO, so they appear as gpio:s8 / gpio:pump / gpio:flushmain:
    SHAMPOO_LINE_DEVICES   = gpio:s8, s1, s2, s4, d1, gpio:pump  (+ p1 dosing)
    DISINFECT_LINE_DEVICES = gpio:s8, s3, s4, s2, d2, gpio:pump  (+ p4 dosing)
    WATER_LINE_DEVICES     = gpio:s8, s5, s2, s4, gpio:pump
    flush_top / flush_bottom = gpio:flushmain, gpio:pump, gpio:top|bottom
    priming shampoo        = fill (gpio:s8,s1,ro1) 60s -> drain (d1,ro2) 10s
    priming disinfectant   = fill (gpio:s8,s3,ro3) 60s -> drain (d2,ro4) 10s
    empty tank             = d1, ro2, d2, ro4           (legacy Empty_tank/drain)

Reference counting: modules share devices (shampoo + conditioner both use the
common bath line; empty tank + priming drain both touch d1/ro2). Each module
contributes its *currently wanted* device set; the controller energises the
union and only drops a relay when no active module still wants it.
=============================================================================
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# Module definitions
# =============================================================================
# Ordered dict drives the on-screen layout. Keys must be URL/JSON safe.
#   type "latch"    -> "devices": [tokens]      (held on until turned off)
#   type "sequence" -> "phases":  [{label, seconds, devices}]  (timed, auto-off)

MANUAL_MODULES: Dict[str, Dict[str, Any]] = {
    "shampoo": {
        "label": "Shampoo",
        "type": "latch",
        "hint": "Shampoo line open + shampoo dosing pump (p1).",
        "devices": ["gpio:s8", "s1", "s2", "s4", "d1", "gpio:pump", "p1"],
    },
    "conditioner": {
        "label": "Conditioner",
        "type": "latch",
        "hint": "Same bath line as shampoo + conditioner dosing pump (p2).",
        "devices": ["gpio:s8", "s1", "s2", "s4", "d1", "gpio:pump", "p2"],
    },
    "disinfectant": {
        "label": "Disinfectant",
        "type": "latch",
        "hint": "Disinfectant line open + disinfectant dosing pump (p4).",
        "devices": ["gpio:s8", "s3", "s4", "s2", "d2", "gpio:pump", "p4"],
    },
    "water": {
        "label": "Water",
        "type": "latch",
        "hint": "Plain water rinse line (no dosing pump).",
        "devices": ["gpio:s8", "s5", "s2", "s4", "gpio:pump"],
    },
    "dryer": {
        "label": "Dryer",
        "type": "latch",
        "hint": "Dryer relay (Pi GPIO 14).",
        "devices": ["gpio:dry"],
    },
    "cleanup_top": {
        "label": "Cleanup Top",
        "type": "latch",
        "hint": "Top flush nozzle opened (bottom stays closed).",
        "devices": ["gpio:flushmain", "gpio:pump", "gpio:top"],
    },
    "cleanup_bottom": {
        "label": "Cleanup Bottom",
        "type": "latch",
        "hint": "Bottom flush nozzle opened (top stays closed).",
        "devices": ["gpio:flushmain", "gpio:pump", "gpio:bottom"],
    },
    "priming_shampoo": {
        "label": "Priming Shampoo",
        "type": "sequence",
        "hint": "Fill shampoo line 60s, then drain 10s (auto-off).",
        "phases": [
            {"label": "Filling",  "seconds": 60, "devices": ["gpio:s8", "s1", "ro1"]},
            {"label": "Draining", "seconds": 10, "devices": ["d1", "ro2"]},
        ],
    },
    "priming_disinfectant": {
        "label": "Priming Disinfectant",
        "type": "sequence",
        "hint": "Fill disinfectant line 60s, then drain 10s (auto-off).",
        "phases": [
            {"label": "Filling",  "seconds": 60, "devices": ["gpio:s8", "s3", "ro3"]},
            {"label": "Draining", "seconds": 10, "devices": ["d2", "ro4"]},
        ],
    },
    "empty_tank": {
        "label": "Empty Tank",
        "type": "latch",
        "hint": "Drain both internal containers (legacy Empty_tank / drain).",
        "devices": ["d1", "ro2", "d2", "ro4"],
    },
}

MODULE_ORDER: List[str] = list(MANUAL_MODULES.keys())


def _module_tokens(spec: Dict[str, Any]) -> List[str]:
    """Flatten every device token a module can touch (latch or sequence)."""
    if spec.get("type") == "sequence":
        seen: List[str] = []
        for phase in spec.get("phases", []):
            for tok in phase.get("devices", []):
                if tok not in seen:
                    seen.append(tok)
        return seen
    return list(spec.get("devices", []))


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
            for tok in _module_tokens(spec)
        ]
        entry: Dict[str, Any] = {
            "key": key,
            "label": spec["label"],
            "type": spec.get("type", "latch"),
            "hint": spec.get("hint", ""),
            "devices": devices,
        }
        if spec.get("type") == "sequence":
            entry["phases"] = [
                {"label": p.get("label", ""), "seconds": int(p.get("seconds", 0))}
                for p in spec.get("phases", [])
            ]
        plan.append(entry)
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
    """Latch + timed-sequence module control with reference-counted relays.

    Construct with the live DeviceController (MQTT) and GPIOController. All
    public methods are thread-safe and return the full state dict so callers
    (HTTP routes) can hand the UI an authoritative snapshot every time.
    """

    def __init__(self, devices, gpio):
        self._devices = devices   # DeviceController (MQTT) or None
        self._gpio = gpio         # GPIOController or None
        self._lock = threading.RLock()
        # key -> set(tokens) the module currently WANTS energised. For latch
        # modules this is the full device set; for sequences it is the current
        # phase's devices (mutated by the worker thread).
        self._active: Dict[str, Set[str]] = {}
        self._energized: Set[str] = set()          # tokens currently held ON
        # Sequence bookkeeping.
        self._threads: Dict[str, threading.Thread] = {}
        self._stops: Dict[str, threading.Event] = {}
        self._runtime: Dict[str, Dict[str, Any]] = {}  # key -> {phase, end}

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
        for tokens in self._active.values():
            want.update(tokens)
        return want

    def _reconcile(self) -> None:
        """Make the energised set match the union of active modules' devices.

        Caller must hold self._lock.
        """
        want = self._desired_tokens()
        for token in want - self._energized:
            if self._set_token(token, True):
                self._energized.add(token)
        for token in list(self._energized - want):
            if self._set_token(token, False):
                self._energized.discard(token)

    # --------------------------------------------------------------- sequences
    def _start_sequence(self, key: str) -> None:
        """Spawn the worker thread for a sequence module (caller holds lock)."""
        if key in self._threads:
            return  # already running
        ev = threading.Event()
        self._stops[key] = ev
        t = threading.Thread(target=self._run_sequence, args=(key, ev),
                             name=f"manual-seq-{key}", daemon=True)
        self._threads[key] = t
        t.start()

    def _run_sequence(self, key: str, ev: threading.Event) -> None:
        phases = MANUAL_MODULES[key].get("phases", [])
        logger.info(f"manual: sequence START -> {key}")
        try:
            for phase in phases:
                if ev.is_set():
                    break
                seconds = float(phase.get("seconds", 0))
                with self._lock:
                    self._active[key] = set(phase.get("devices", []))
                    self._runtime[key] = {
                        "phase": phase.get("label", ""),
                        "end": time.time() + seconds,
                    }
                    self._reconcile()
                # Interruptible wait — returns True the instant we're aborted.
                if ev.wait(seconds):
                    break
        finally:
            with self._lock:
                self._active.pop(key, None)
                self._runtime.pop(key, None)
                self._stops.pop(key, None)
                self._threads.pop(key, None)
                self._reconcile()
            logger.info(f"manual: sequence END   -> {key}"
                        f"{' (aborted)' if ev.is_set() else ''}")

    def _stop_sequence(self, key: str) -> None:
        """Signal a running sequence to abort and wait briefly for cleanup."""
        with self._lock:
            ev = self._stops.get(key)
            t = self._threads.get(key)
        if ev is not None:
            ev.set()
        if t is not None:
            t.join(timeout=1.0)  # worker wakes immediately; cleanup is fast

    # ---------------------------------------------------------------- public API
    def set_module(self, key: str, on: bool) -> Dict[str, Any]:
        spec = MANUAL_MODULES.get(key)
        if spec is None:
            raise KeyError(key)
        is_sequence = spec.get("type") == "sequence"

        if is_sequence:
            if on:
                with self._lock:
                    self._start_sequence(key)
                    logger.info(f"manual: module ON  -> {key} (sequence)")
            else:
                logger.info(f"manual: module OFF -> {key} (abort sequence)")
                self._stop_sequence(key)
            return self.state()

        # Latch module.
        with self._lock:
            if on:
                self._active[key] = set(spec.get("devices", []))
                logger.info(f"manual: module ON  -> {key}")
            else:
                self._active.pop(key, None)
                logger.info(f"manual: module OFF -> {key}")
            self._reconcile()
            return self._state_locked()

    def all_off(self) -> Dict[str, Any]:
        logger.warning("manual: ALL OFF (operator)")
        # Abort sequences outside the lock (join), then clear everything.
        with self._lock:
            running = list(self._stops.keys())
        for key in running:
            self._stop_sequence(key)
        with self._lock:
            self._active.clear()
            self._runtime.clear()
            for token in list(self._energized):
                self._set_token(token, False)
            self._energized.clear()
            return self._state_locked()

    @property
    def any_active(self) -> bool:
        with self._lock:
            return bool(self._active) or bool(self._threads)

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> Dict[str, Any]:
        now = time.time()
        status: Dict[str, str] = {}
        for key, rt in self._runtime.items():
            remaining = max(0, int(round(rt.get("end", now) - now)))
            phase = rt.get("phase", "")
            status[key] = f"{phase} — {remaining}s" if phase else f"{remaining}s"
        active_keys = set(self._active.keys()) | set(self._threads.keys())
        return {
            "modules": {k: (k in active_keys) for k in MODULE_ORDER},
            "status": status,
            "energized": sorted(self._energized),
            "any_active": bool(active_keys),
        }
