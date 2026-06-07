"""
=============================================================================
GPIO Controller - Direct Raspberry Pi GPIO Control - Project Spotless
=============================================================================
Controls relays directly connected to the Raspberry Pi 5 GPIO header.

These are NOT connected through the ESP32 nodes and NOT through the HAT's
MCP23017 I2C expander — they are wired straight to the Pi's 40-pin GPIO
header and driven by NPN (MMBT3904) transistor stages (active-HIGH).

Direct GPIO Relays:
    dry     - GPIO 14 - Dryer Relay
    roof    - GPIO 15 - Roof Light (tubelight)
    geyser  - GPIO 18 - Geyser/Heater Relay
    top     - GPIO 20 - Flush Top Nozzle    (moved off ESP32 Node 2)
    bottom  - GPIO 21 - Flush Bottom Nozzle  (moved off ESP32 Node 3)
    rglight - GPIO 24 - Red/Green Indicator Light

libgpiod compatibility
----------------------
Raspberry Pi 5 / Bookworm ships libgpiod **2.x**, whose Python API is
completely different from the old 1.x API. This module supports BOTH:
  - v2 (preferred): gpiod.request_lines(...) + gpiod.line.Value/Direction
  - v1 (fallback):  gpiod.Chip(...).get_line(...).request(...)
If neither real backend can be initialised the controller runs in an
EXPLICIT simulated mode and logs an error (it will not pretend to work).

Usage:
    from gpio_controller import GPIOController

    gpio = GPIOController()
    gpio.dry.on()        # Turn on dryer
    gpio.dry.off()       # Turn off dryer
    gpio.geyser.on()     # Turn on geyser
    gpio.flushmain.on()  # Turn on autoflush gate (was 'roof' pin)
    gpio.pump.on()       # Turn on booster pump
    gpio.s8.on()         # Turn on main gate (bath lines)
    gpio.top.on()        # Turn on flush top nozzle
    gpio.bottom.on()     # Turn on flush bottom nozzle
    gpio.rglight.on()    # Turn on indicator light
    gpio.all_off()       # Turn off all GPIO relays
=============================================================================
"""

import glob
import logging
import os
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Detect gpiod and which API version is installed
# =============================================================================
# GPIO_AVAILABLE   - a usable gpiod module was imported
# GPIOD_API        - "v2" | "v1" | None
GPIO_AVAILABLE = False
GPIOD_API: Optional[str] = None
_V2_Direction = None
_V2_Value = None

try:
    import gpiod  # type: ignore

    # v2 exposes request_lines() at module level and gpiod.line.{Value,Direction}.
    # v1 exposes Chip(...).get_line() and gpiod.LINE_REQ_DIR_OUT.
    if hasattr(gpiod, "request_lines") or hasattr(gpiod, "LineSettings"):
        try:
            from gpiod.line import Direction as _V2_Direction  # type: ignore
            from gpiod.line import Value as _V2_Value          # type: ignore
            GPIOD_API = "v2"
            GPIO_AVAILABLE = True
        except Exception as e:  # pragma: no cover - import edge cases
            logger.error(f"gpiod v2 present but gpiod.line import failed: {e}")
    elif hasattr(gpiod, "Chip") and hasattr(gpiod, "LINE_REQ_DIR_OUT"):
        GPIOD_API = "v1"
        GPIO_AVAILABLE = True
    else:
        logger.error("gpiod imported but neither v1 nor v2 API was detected.")
except ImportError:
    logger.warning(
        "gpiod not available - GPIO control will be SIMULATED. "
        "On a real Pi 5 install it with: sudo apt install python3-libgpiod"
    )


# =============================================================================
# GPIO Pin Configuration
# =============================================================================
# Candidate chip paths. On Pi 5 the 40-pin header lives on the RP1 chip whose
# label is "pinctrl-rp1"; depending on kernel that is /dev/gpiochip0 (current)
# or /dev/gpiochip4 (older). We auto-detect by label and fall back to these.
GPIO_CHIP_CANDIDATES = ("/dev/gpiochip0", "/dev/gpiochip4")
GPIO_CHIP_LABEL_HINTS = ("pinctrl-rp1", "rp1")

# Direct GPIO Relay Pins (BCM numbering)
# NOTE: 'roof' retired - GPIO 15 is now 'flushmain' (autoflush gate, moved off
# ESP32). 's8' and 'pump' also moved off the ESP32 nodes onto direct Pi GPIO.
GPIO_PINS = {
    "dry": 14,        # Dryer Relay - GPIO 14
    "flushmain": 15,  # Autoflush Gate 220V - GPIO 15 (moved from ESP32; was 'roof')
    "geyser": 18,     # Geyser/Heater Relay - GPIO 18
    "top": 20,        # Flush Top Nozzle - GPIO 20 (moved from ESP32 Node 2)
    "bottom": 21,     # Flush Bottom Nozzle - GPIO 21 (moved from ESP32 Node 3)
    "pump": 23,       # Booster Pump 220V - GPIO 23 (moved from ESP32 Node 1)
    "rglight": 24,    # Red/Green Indicator Light - GPIO 24
    "s8": 25,         # Main Gate 220V (bath lines) - GPIO 25 (moved from ESP32)
}

# Relay active state. Most channels are driven through an NPN transistor
# (base HIGH -> relay ON) and are therefore ACTIVE-HIGH.
GPIO_ACTIVE_STATE = True  # default for relays NOT listed in GPIO_ACTIVE_LOW

# Per-relay overrides: these channels are wired ACTIVE-LOW (relay ON when the
# pin is LOW). They were observed energised at boot and inverted vs the rest,
# so we drive them the opposite way to the default. dry + geyser were the
# original two; s8, flushmain and pump (newly moved onto Pi GPIO) are wired the
# same active-LOW way on this relay board.
GPIO_ACTIVE_LOW = {"dry", "geyser", "s8", "flushmain", "pump"}


def _relay_active_high(name: str) -> bool:
    """Effective active-high flag for a single relay (honours overrides)."""
    return (not GPIO_ACTIVE_STATE) if name in GPIO_ACTIVE_LOW else GPIO_ACTIVE_STATE


def _physical_high(name: str, state: bool) -> bool:
    """Map a relay's logical ON/OFF to the physical pin level."""
    return state if _relay_active_high(name) else (not state)


# =============================================================================
# GPIO Relay Handle
# =============================================================================
class GPIORelay:
    """Handle for controlling a single GPIO relay.

    `writer` is a callable(bool)->bool that performs the actual hardware write
    (already accounting for active-high/low). When it is None the relay is in
    simulated mode and state is tracked in software only.
    """

    def __init__(self, name: str, pin: int, writer: Optional[Callable[[bool], bool]] = None):
        self.name = name
        self.pin = pin
        self._writer = writer
        self._state = False

    def on(self) -> bool:
        return self.set(True)

    def off(self) -> bool:
        return self.set(False)

    def set(self, state: bool) -> bool:
        try:
            ok = True
            if self._writer is not None:
                ok = self._writer(state)
            self._state = state
            logger.info(f"GPIO {self.name} (pin {self.pin}): {'ON' if state else 'OFF'}"
                        f"{'' if self._writer is not None else ' [SIMULATED]'}")
            return ok
        except Exception as e:
            logger.error(f"Failed to set GPIO {self.name} (pin {self.pin}): {e}")
            return False

    @property
    def state(self) -> bool:
        return self._state

    def __repr__(self):
        return f"GPIORelay({self.name}, pin={self.pin}, state={'ON' if self._state else 'OFF'})"


# =============================================================================
# GPIO Controller
# =============================================================================
class GPIOController:
    """Controller for direct Raspberry Pi GPIO relays (native header pins)."""

    def __init__(self, auto_init: bool = True):
        self._chip = None                 # v1 chip handle
        self._request = None              # v2 line request handle
        self._lines: Dict[str, any] = {}  # v1 per-line handles
        self._relays: Dict[str, GPIORelay] = {}
        self._initialized = False
        self.backend = "none"             # "gpiod-v2" | "gpiod-v1" | "simulated"
        self.hardware_ok = False
        self.chip_path: Optional[str] = None

        if auto_init:
            self.initialize()

    # -------------------------------------------------------------------------
    # Initialisation
    # -------------------------------------------------------------------------
    def initialize(self) -> bool:
        logger.info("Initializing Raspberry Pi GPIO controller...")
        logger.info(f"GPIO Pins: {GPIO_PINS}  (active_high={GPIO_ACTIVE_STATE})")

        if not GPIO_AVAILABLE:
            logger.error(
                "gpiod is not usable on this host - relays will be SIMULATED. "
                "If this is the real Pi, install python3-libgpiod and restart."
            )
            self._init_simulated()
            return False

        try:
            if GPIOD_API == "v2":
                ok = self._init_v2()
            else:
                ok = self._init_v1()
            if ok:
                self._initialized = True
                self.hardware_ok = True
                logger.info(f"GPIO controller initialized ({self.backend}, chip={self.chip_path})")
                return True
            raise RuntimeError("no GPIO lines could be initialised")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO controller ({GPIOD_API}): {e}")
            logger.error("Falling back to SIMULATED relays - hardware will NOT switch.")
            self._init_simulated()
            return False

    # ---- chip discovery -----------------------------------------------------
    def _discover_chip_path(self) -> Optional[str]:
        """Find the 40-pin header chip by label, fall back to known paths."""
        paths = sorted(glob.glob("/dev/gpiochip*"))
        # 1) Prefer a chip whose label looks like the RP1 header controller.
        for path in paths:
            label = self._chip_label(path)
            if label and any(h in label.lower() for h in GPIO_CHIP_LABEL_HINTS):
                return path
        # 2) Known candidate paths that exist.
        for path in GPIO_CHIP_CANDIDATES:
            if os.path.exists(path):
                return path
        # 3) Anything at all.
        return paths[0] if paths else None

    def _chip_label(self, path: str) -> Optional[str]:
        try:
            if GPIOD_API == "v2":
                chip = gpiod.Chip(path)
                try:
                    return chip.get_info().label
                finally:
                    chip.close()
            else:  # v1
                chip = gpiod.Chip(path)
                try:
                    # v1: Chip.label or name()
                    return getattr(chip, "label", None) or chip.name()
                finally:
                    chip.close()
        except Exception:
            return None

    # ---- libgpiod v2 --------------------------------------------------------
    def _init_v2(self) -> bool:
        self.chip_path = self._discover_chip_path()
        if not self.chip_path:
            raise RuntimeError("no /dev/gpiochip* device found")

        # Build one request for all relay pins, each initialised to its own
        # physical OFF level (active-low channels idle HIGH, others idle LOW).
        config = {}
        for name, pin in GPIO_PINS.items():
            off_high = _physical_high(name, False)
            config[pin] = gpiod.LineSettings(
                direction=_V2_Direction.OUTPUT,
                output_value=_V2_Value.ACTIVE if off_high else _V2_Value.INACTIVE,
            )

        if hasattr(gpiod, "request_lines"):
            self._request = gpiod.request_lines(
                self.chip_path, consumer="spotless_gpio", config=config
            )
        else:  # some 2.x builds only expose Chip.request_lines
            chip = gpiod.Chip(self.chip_path)
            self._request = chip.request_lines(consumer="spotless_gpio", config=config)

        for name, pin in GPIO_PINS.items():
            self._relays[name] = GPIORelay(name, pin, self._make_v2_writer(name, pin))
            logger.info(f"  Initialized GPIO {name}: pin {pin} - OFF"
                        f"{' (active-low)' if name in GPIO_ACTIVE_LOW else ''}")

        self.backend = "gpiod-v2"
        return True

    def _make_v2_writer(self, name: str, pin: int) -> Callable[[bool], bool]:
        def _write(state: bool) -> bool:
            value = _V2_Value.ACTIVE if _physical_high(name, state) else _V2_Value.INACTIVE
            self._request.set_value(pin, value)
            return True
        return _write

    # ---- libgpiod v1 --------------------------------------------------------
    def _init_v1(self) -> bool:
        self.chip_path = self._discover_chip_path() or GPIO_CHIP_CANDIDATES[0]
        self._chip = gpiod.Chip(self.chip_path)
        logger.info(f"Opened GPIO chip: {self.chip_path}")

        any_ok = False
        for name, pin in GPIO_PINS.items():
            try:
                line = self._chip.get_line(pin)
                line.request(consumer="spotless_gpio", type=gpiod.LINE_REQ_DIR_OUT)
                line.set_value(1 if _physical_high(name, False) else 0)
                self._lines[name] = line
                self._relays[name] = GPIORelay(name, pin, self._make_v1_writer(name, line))
                any_ok = True
                logger.info(f"  Initialized GPIO {name}: pin {pin} - OFF"
                            f"{' (active-low)' if name in GPIO_ACTIVE_LOW else ''}")
            except Exception as e:
                logger.error(f"  Failed to initialize GPIO {name} (pin {pin}): {e}")
                self._relays[name] = GPIORelay(name, pin, None)

        self.backend = "gpiod-v1"
        return any_ok

    def _make_v1_writer(self, name: str, line) -> Callable[[bool], bool]:
        def _write(state: bool) -> bool:
            line.set_value(1 if _physical_high(name, state) else 0)
            return True
        return _write

    # ---- simulated ----------------------------------------------------------
    def _init_simulated(self):
        self._relays.clear()
        for name, pin in GPIO_PINS.items():
            self._relays[name] = GPIORelay(name, pin, None)
            logger.info(f"  Created SIMULATED GPIO {name}: pin {pin}")
        self.backend = "simulated"
        self.hardware_ok = False
        self._initialized = True

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------
    def cleanup(self):
        logger.info("Cleaning up GPIO controller...")
        try:
            self.all_off()
        except Exception:
            pass

        # v2: release the single request.
        if self._request is not None:
            try:
                self._request.release()
            except Exception as e:
                logger.warning(f"Error releasing GPIO request: {e}")
            self._request = None

        # v1: release each line + chip.
        for name, line in self._lines.items():
            try:
                if line is not None:
                    line.release()
            except Exception as e:
                logger.warning(f"Error releasing GPIO {name}: {e}")
        self._lines.clear()
        if self._chip is not None:
            try:
                self._chip.close()
            except Exception:
                pass
            self._chip = None

        self._initialized = False
        logger.info("GPIO controller cleanup complete")

    # =========================================================================
    # Relay Access Properties
    # =========================================================================
    @property
    def dry(self) -> GPIORelay:
        return self._relays.get("dry")

    @property
    def roof(self) -> GPIORelay:
        # 'roof' retired (GPIO 15 reused by flushmain). Returns None so the
        # optional RoofLightController degrades to a harmless no-op.
        return self._relays.get("roof")

    @property
    def flushmain(self) -> GPIORelay:
        return self._relays.get("flushmain")

    @property
    def pump(self) -> GPIORelay:
        return self._relays.get("pump")

    @property
    def s8(self) -> GPIORelay:
        return self._relays.get("s8")

    @property
    def geyser(self) -> GPIORelay:
        return self._relays.get("geyser")

    @property
    def top(self) -> GPIORelay:
        return self._relays.get("top")

    @property
    def bottom(self) -> GPIORelay:
        return self._relays.get("bottom")

    @property
    def rglight(self) -> GPIORelay:
        return self._relays.get("rglight")

    # =========================================================================
    # Control Methods
    # =========================================================================
    def get_relay(self, name: str) -> Optional[GPIORelay]:
        return self._relays.get(name)

    def set_relay(self, name: str, state: bool) -> bool:
        relay = self._relays.get(name)
        if relay:
            return relay.set(state)
        logger.error(f"Unknown GPIO relay: {name}")
        return False

    def all_off(self) -> bool:
        logger.info("Turning OFF all GPIO relays")
        success = True
        for name, relay in self._relays.items():
            if not relay.off():
                success = False
        return success

    def all_on(self) -> bool:
        logger.warning("Turning ON all GPIO relays")
        success = True
        for name, relay in self._relays.items():
            if not relay.on():
                success = False
        return success

    def get_states(self) -> Dict[str, bool]:
        return {name: relay.state for name, relay in self._relays.items()}

    def list_relays(self) -> List[Dict]:
        return [
            {"name": name, "pin": relay.pin, "state": "ON" if relay.state else "OFF"}
            for name, relay in self._relays.items()
        ]

    def print_status(self):
        print("\n" + "=" * 50)
        print("  Raspberry Pi GPIO Relays - Status")
        print(f"  backend={self.backend}  hardware_ok={self.hardware_ok}  chip={self.chip_path}")
        print("=" * 50)
        for name, relay in self._relays.items():
            state_str = "ON" if relay.state else "OFF"
            print(f"  {name:10} (GPIO {relay.pin:2}): {state_str}")
        print("=" * 50 + "\n")

    # =========================================================================
    # Context Manager Support
    # =========================================================================
    def __enter__(self):
        if not self._initialized:
            self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False


# =============================================================================
# Global Instance (optional)
# =============================================================================
_gpio_instance: Optional[GPIOController] = None


def get_gpio_controller() -> GPIOController:
    global _gpio_instance
    if _gpio_instance is None:
        _gpio_instance = GPIOController()
    return _gpio_instance


# =============================================================================
# Convenience Functions
# =============================================================================
def dry_on():
    return get_gpio_controller().dry.on()


def dry_off():
    return get_gpio_controller().dry.off()


def geyser_on():
    return get_gpio_controller().geyser.on()


def geyser_off():
    return get_gpio_controller().geyser.off()


# =============================================================================
# Main - Test when run directly
# =============================================================================
if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    print("GPIO Controller Test")
    print("-" * 40)
    print(f"gpiod available : {GPIO_AVAILABLE}  (API: {GPIOD_API})")

    gpio = GPIOController()
    gpio.print_status()

    if not gpio.hardware_ok:
        print("\n[!] Running in SIMULATED mode - no real switching will happen.")
        print("    On the Pi: sudo apt install python3-libgpiod  (then re-run).")

    # Walk every relay for 1s so you can hear/see each click.
    for name in GPIO_PINS:
        print(f"\nPulsing {name} for 1s...")
        gpio.set_relay(name, True)
        time.sleep(1)
        gpio.set_relay(name, False)

    print("\nAll off...")
    gpio.all_off()
    gpio.print_status()

    gpio.cleanup()
    print("\nTest complete!")
