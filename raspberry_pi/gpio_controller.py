"""
=============================================================================
GPIO Controller - Direct Raspberry Pi GPIO Control - Project Spotless
=============================================================================
Controls relays directly connected to the Raspberry Pi GPIO pins.

These are NOT connected through ESP32 nodes - they are directly wired to
the Raspberry Pi 5 GPIO header.

Direct GPIO Relays:
    dry    - GPIO 14 - Dryer Relay
    geyser - GPIO 18 - Geyser/Heater Relay

Usage:
    from gpio_controller import GPIOController
    
    gpio = GPIOController()
    gpio.dry.on()      # Turn on dryer
    gpio.dry.off()     # Turn off dryer
    gpio.geyser.on()   # Turn on geyser
    gpio.all_off()     # Turn off all GPIO relays
=============================================================================
"""

import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Try to import gpiod (Raspberry Pi 5 GPIO library)
try:
    import gpiod
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("gpiod not available - GPIO control will be simulated")


# =============================================================================
# GPIO Pin Configuration
# =============================================================================
GPIO_CHIP = "gpiochip0"  # Raspberry Pi 5 GPIO chip

# Direct GPIO Relay Pins
GPIO_PINS = {
    "dry": 14,      # Dryer Relay - GPIO 14
    "geyser": 18,   # Geyser/Heater Relay - GPIO 18
}

# Relay active state (HIGH = relay ON for most relay modules)
GPIO_ACTIVE_STATE = True  # True = Active HIGH, False = Active LOW


# =============================================================================
# GPIO Relay Handle
# =============================================================================
class GPIORelay:
    """Handle for controlling a single GPIO relay."""
    
    def __init__(self, name: str, pin: int, line=None):
        self.name = name
        self.pin = pin
        self._line = line
        self._state = False
        
    def on(self) -> bool:
        """Turn the relay ON."""
        return self.set(True)
        
    def off(self) -> bool:
        """Turn the relay OFF."""
        return self.set(False)
        
    def set(self, state: bool) -> bool:
        """Set relay state."""
        try:
            if self._line is not None:
                value = 1 if state else 0
                if not GPIO_ACTIVE_STATE:
                    value = 1 - value  # Invert for active low
                self._line.set_value(value)
            
            self._state = state
            logger.info(f"GPIO {self.name} (pin {self.pin}): {'ON' if state else 'OFF'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set GPIO {self.name}: {e}")
            return False
            
    @property
    def state(self) -> bool:
        """Get current relay state."""
        return self._state
        
    def __repr__(self):
        return f"GPIORelay({self.name}, pin={self.pin}, state={'ON' if self._state else 'OFF'})"


# =============================================================================
# GPIO Controller
# =============================================================================
class GPIOController:
    """
    Controller for direct Raspberry Pi GPIO relays.
    
    Manages relays that are directly connected to the Pi's GPIO pins,
    separate from the ESP32-controlled relays.
    """
    
    def __init__(self, auto_init: bool = True):
        self._chip = None
        self._lines: Dict[str, any] = {}
        self._relays: Dict[str, GPIORelay] = {}
        self._initialized = False
        
        if auto_init:
            self.initialize()
            
    def initialize(self) -> bool:
        """Initialize GPIO pins."""
        logger.info("Initializing Raspberry Pi GPIO controller...")
        logger.info(f"GPIO Pins: {GPIO_PINS}")
        
        if not GPIO_AVAILABLE:
            logger.warning("gpiod not available - creating simulated GPIO relays")
            self._create_simulated_relays()
            return True
            
        try:
            # Open GPIO chip
            self._chip = gpiod.Chip(GPIO_CHIP)
            logger.info(f"Opened GPIO chip: {GPIO_CHIP}")
            
            # Initialize each relay pin
            for name, pin in GPIO_PINS.items():
                try:
                    line = self._chip.get_line(pin)
                    line.request(consumer="spotless_gpio", type=gpiod.LINE_REQ_DIR_OUT)
                    
                    # Initialize to OFF state
                    initial_value = 0 if GPIO_ACTIVE_STATE else 1
                    line.set_value(initial_value)
                    
                    self._lines[name] = line
                    self._relays[name] = GPIORelay(name, pin, line)
                    
                    logger.info(f"  Initialized GPIO {name}: pin {pin} - OFF")
                    
                except Exception as e:
                    logger.error(f"  Failed to initialize GPIO {name} (pin {pin}): {e}")
                    self._relays[name] = GPIORelay(name, pin, None)
                    
            self._initialized = True
            logger.info("GPIO controller initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize GPIO controller: {e}")
            self._create_simulated_relays()
            return False
            
    def _create_simulated_relays(self):
        """Create simulated relays when GPIO is not available."""
        for name, pin in GPIO_PINS.items():
            self._relays[name] = GPIORelay(name, pin, None)
            logger.info(f"  Created simulated GPIO {name}: pin {pin}")
        self._initialized = True
        
    def cleanup(self):
        """Cleanup GPIO resources."""
        logger.info("Cleaning up GPIO controller...")
        
        # Turn off all relays first
        self.all_off()
        
        # Release GPIO lines
        for name, line in self._lines.items():
            try:
                if line is not None:
                    line.release()
                    logger.debug(f"Released GPIO line: {name}")
            except Exception as e:
                logger.warning(f"Error releasing GPIO {name}: {e}")
                
        self._lines.clear()
        self._initialized = False
        logger.info("GPIO controller cleanup complete")
        
    # =========================================================================
    # Relay Access Properties
    # =========================================================================
    
    @property
    def dry(self) -> GPIORelay:
        """Access dry relay (GPIO 14)."""
        return self._relays.get("dry")
    
    @property
    def geyser(self) -> GPIORelay:
        """Access geyser relay (GPIO 18)."""
        return self._relays.get("geyser")
        
    # =========================================================================
    # Control Methods
    # =========================================================================
    
    def get_relay(self, name: str) -> Optional[GPIORelay]:
        """Get a relay by name."""
        return self._relays.get(name)
        
    def set_relay(self, name: str, state: bool) -> bool:
        """Set a relay state by name."""
        relay = self._relays.get(name)
        if relay:
            return relay.set(state)
        logger.error(f"Unknown GPIO relay: {name}")
        return False
        
    def all_off(self) -> bool:
        """Turn off all GPIO relays."""
        logger.info("Turning OFF all GPIO relays")
        success = True
        for name, relay in self._relays.items():
            if not relay.off():
                success = False
        return success
        
    def all_on(self) -> bool:
        """Turn on all GPIO relays (use with caution!)."""
        logger.warning("Turning ON all GPIO relays")
        success = True
        for name, relay in self._relays.items():
            if not relay.on():
                success = False
        return success
        
    def get_states(self) -> Dict[str, bool]:
        """Get states of all relays."""
        return {name: relay.state for name, relay in self._relays.items()}
        
    def list_relays(self) -> List[Dict]:
        """List all configured GPIO relays."""
        return [
            {
                "name": name,
                "pin": relay.pin,
                "state": "ON" if relay.state else "OFF"
            }
            for name, relay in self._relays.items()
        ]
        
    def print_status(self):
        """Print status of all GPIO relays."""
        print("\n" + "=" * 50)
        print("  Raspberry Pi GPIO Relays - Status")
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
    """Get or create the global GPIO controller instance."""
    global _gpio_instance
    if _gpio_instance is None:
        _gpio_instance = GPIOController()
    return _gpio_instance


# =============================================================================
# Convenience Functions
# =============================================================================
def dry_on():
    """Turn on dryer relay."""
    return get_gpio_controller().dry.on()

def dry_off():
    """Turn off dryer relay."""
    return get_gpio_controller().dry.off()

def geyser_on():
    """Turn on geyser relay."""
    return get_gpio_controller().geyser.on()

def geyser_off():
    """Turn off geyser relay."""
    return get_gpio_controller().geyser.off()


# =============================================================================
# Main - Test when run directly
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("GPIO Controller Test")
    print("-" * 40)
    
    gpio = GPIOController()
    gpio.print_status()
    
    print("\nTesting dry relay...")
    gpio.dry.on()
    gpio.print_status()
    
    print("\nTesting geyser relay...")
    gpio.geyser.on()
    gpio.print_status()
    
    print("\nAll off...")
    gpio.all_off()
    gpio.print_status()
    
    gpio.cleanup()
    print("\nTest complete!")
