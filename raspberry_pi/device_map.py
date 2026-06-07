"""
=============================================================================
Device Mapping - Project Spotless
=============================================================================
Maps friendly variable names to ESP32 node + relay combinations.

This module provides easy-to-use variable names that correspond to specific
relays on specific ESP32 nodes, matching the physical hardware layout.

Usage:
    from device_map import devices, DeviceController
    
    # Get device info
    devices.p1  # Returns DeviceInfo for Node 1, Relay 7 (BACK2)
    
    # With DeviceController
    dc = DeviceController(node_controller)
    dc.p1.on()       # Turn on peristaltic pump 1 (shampoo)
    dc.p2.on()       # Turn on peristaltic pump 2 (conditioner)
    # Note: pump, flushmain and s8 are now Pi-direct GPIO (gpio_controller),
    # addressed as "gpio:pump" / "gpio:flushmain" / "gpio:s8" in stage data.

Node/Relay Mapping (BACK2 / Relay 7 retired — faulty relay channel):
    NODE 1 (spotless_node1) — Container 1 system:
        --   → S1       (Relay 1) - UNUSED (pump moved to Pi GPIO 23)
        p1   → P1&P2    (Relay 2) - Peristaltic Pump 1 (Shampoo)   [moved from BACK2]
        d1   → FP1      (Relay 3) - Diaphragm Pump 1 (Push from Container 1)
        ro2  → RS1&DS2  (Relay 4) - RO Solenoid 2 (Drain Container 1)
        ro1  → RS2&DS1  (Relay 5) - RO Solenoid 1 (Fill Container 1)
        p2   → BACK1    (Relay 6) - Peristaltic Pump 2 (Conditioner)
        --   → BACK2    (Relay 7) - BLANK / unused

    NODE 2 (spotless_node2) — Container 2 system + Autoflush:
        --       → S1       (Relay 1) - UNUSED (flushmain moved to Pi GPIO 15)
        p3       → P1&P2    (Relay 2) - Peristaltic Pump 3 (Med Shampoo) [moved from Node 1]
        d2       → FP1      (Relay 3) - Diaphragm Pump 2 (Push from Container 2)
        ro4      → RS1&DS2  (Relay 4) - RO Solenoid 4 (Drain Container 2)
        ro3      → RS2&DS1  (Relay 5) - RO Solenoid 3 (Fill Container 2)
        p4       → BACK1    (Relay 6) - Peristaltic Pump 4 (Disinfectant) [replaced p5 backup]
        --       → BACK2    (Relay 7) - BLANK / unused

    NODE 3 (spotless_node3) — Bath line solenoid valves:
        --     → S1       (Relay 1) - UNUSED (s8 moved to Pi GPIO 25)
        s1     → P1&P2    (Relay 2) - Solenoid 1 (Shampoo line gate)   [moved from BACK2]
        s5     → FP1      (Relay 3) - Solenoid 5 (Water line)
        s4     → RS1&DS2  (Relay 4) - Solenoid 4 (Common valve / anti-backflow)
        s3     → RS2&DS1  (Relay 5) - Solenoid 3 (Disinfectant line gate)
        s2     → BACK1    (Relay 6) - Solenoid 2 (Common spray / anti-backflow)
        --     → BACK2    (Relay 7) - BLANK / unused

    DISPLACED DEVICES (re-homed off the ESP32 nodes, now Pi-direct GPIO):
        top       - Flush Top Nozzle    -> Raspberry Pi GPIO 20 (gpio_controller.py)
        bottom    - Flush Bottom Nozzle -> Raspberry Pi GPIO 21 (gpio_controller.py)
        pump      - Booster Pump 220V   -> Raspberry Pi GPIO 23 (gpio_controller.py)
        flushmain - Autoflush Gate 220V -> Raspberry Pi GPIO 15 (gpio_controller.py)
        s8        - Main Gate 220V      -> Raspberry Pi GPIO 25 (gpio_controller.py)
        roof      - RETIRED (GPIO 15 reused by flushmain)
        p5        - Peristaltic Pump 5 (Backup) -> DROPPED (replaced by p4 on Node 2 BACK1)
=============================================================================
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Relay Number Constants (identical PCB layout on all 3 nodes)
# =============================================================================
RELAY_S1_220V = 1      # S1 (220V Solenoid)
RELAY_P1_P2 = 2        # P1&P2 (Pumps)
RELAY_FP1 = 3          # FP1 (Flow Pump 1)
RELAY_RS1_DS2 = 4      # RS1&DS2
RELAY_RS2_DS1 = 5      # RS2&DS1
RELAY_BACK1 = 6        # BACK1 (Backflow 1)
RELAY_BACK2 = 7        # BACK2 (Backflow 2)

# =============================================================================
# Node IDs
# =============================================================================
NODE_1 = "spotless_node1"
NODE_2 = "spotless_node2"
NODE_3 = "spotless_node3"


# =============================================================================
# Device Mapping Class
# =============================================================================
@dataclass
class DeviceInfo:
    """Information about a device (relay on a specific node)."""
    name: str           # Variable name (e.g., "p1", "ro1", "top")
    node_id: str        # ESP32 node ID
    relay_num: int      # Relay number (1-7)
    relay_label: str    # PCB relay label (e.g., "BACK2", "RS1_DS2")
    description: str    # Human-readable description
    
    def __repr__(self):
        return f"Device({self.name}: {self.node_id} → Relay {self.relay_num} [{self.relay_label}])"
    
    def as_tuple(self) -> Tuple[str, int]:
        """Return (node_id, relay_num) tuple."""
        return (self.node_id, self.relay_num)


class DeviceMap:
    """Maps friendly variable names to node+relay combinations."""
    
    def __init__(self):
        self._devices = {}
        self._setup_mappings()
        
    def _setup_mappings(self):
        # =====================================================================
        # NODE 1 — Container 1 system (spotless_node1)
        # =====================================================================
        # BACK2 (Relay 7) retired - faulty relay channel.
        #   p1 (shampoo pump) re-homed BACK2 -> P1_P2 (Relay 2).
        #   p3 (med shampoo) relocated to Node 2 (Relay 2). Relay 7 left blank.
        #   pump (Booster 220V) moved off Relay 1 -> Pi GPIO 23 ("gpio:pump").
        self._add("p1", NODE_1, RELAY_P1_P2, "P1_P2",
                  "Peristaltic Pump 1 — Shampoo")
        self._add("d1", NODE_1, RELAY_FP1, "FP1",
                  "Diaphragm Pump 1 — Push from Container 1")
        self._add("ro2", NODE_1, RELAY_RS1_DS2, "RS1_DS2",
                  "RO Solenoid 2 — Drain Container 1")
        self._add("ro1", NODE_1, RELAY_RS2_DS1, "RS2_DS1",
                  "RO Solenoid 1 — Fill Container 1")
        self._add("p2", NODE_1, RELAY_BACK1, "BACK1",
                  "Peristaltic Pump 2 — Conditioner")
        # Relay 7 (BACK2) — BLANK / unused

        # =====================================================================
        # NODE 2 — Container 2 system + Autoflush (spotless_node2)
        # =====================================================================
        # BACK2 (Relay 7) retired - faulty relay channel.
        #   p3 (med shampoo, relocated from Node 1) now on P1_P2 (Relay 2).
        #   p4 (disinfectant) now on BACK1 (Relay 6) — replaced p5 backup.
        #   top -> Pi GPIO 20 (gpio_controller). Relay 7 left blank.
        #   flushmain (Autoflush 220V) moved off Relay 1 -> Pi GPIO 15
        #     ("gpio:flushmain"; GPIO 15 was the retired 'roof').
        self._add("p3", NODE_2, RELAY_P1_P2, "P1_P2",
                  "Peristaltic Pump 3 — Med Shampoo")
        self._add("d2", NODE_2, RELAY_FP1, "FP1",
                  "Diaphragm Pump 2 — Push from Container 2")
        self._add("ro4", NODE_2, RELAY_RS1_DS2, "RS1_DS2",
                  "RO Solenoid 4 — Drain Container 2")
        self._add("ro3", NODE_2, RELAY_RS2_DS1, "RS2_DS1",
                  "RO Solenoid 3 — Fill Container 2")
        self._add("p4", NODE_2, RELAY_BACK1, "BACK1",
                  "Peristaltic Pump 4 — Disinfectant")
        # Relay 7 (BACK2) — BLANK / unused

        # =====================================================================
        # NODE 3 — Bath line solenoid valves (spotless_node3)
        # =====================================================================
        # BACK2 (Relay 7) retired - faulty relay channel.
        #   s1 (shampoo line gate) re-homed BACK2 -> P1_P2 (Relay 2).
        #   bottom -> Pi GPIO 21 (gpio_controller). Relay 7 left blank.
        #   s8 (Main Gate 220V) moved off Relay 1 -> Pi GPIO 25 ("gpio:s8").
        self._add("s1", NODE_3, RELAY_P1_P2, "P1_P2",
                  "Solenoid 1 — Shampoo line gate")
        self._add("s5", NODE_3, RELAY_FP1, "FP1",
                  "Solenoid 5 — Water line")
        self._add("s4", NODE_3, RELAY_RS1_DS2, "RS1_DS2",
                  "Solenoid 4 — Common valve / anti-backflow")
        self._add("s3", NODE_3, RELAY_RS2_DS1, "RS2_DS1",
                  "Solenoid 3 — Disinfectant line gate")
        self._add("s2", NODE_3, RELAY_BACK1, "BACK1",
                  "Solenoid 2 — Common spray / anti-backflow")
        # Relay 7 (BACK2) — BLANK / unused

        # =====================================================================
        # DISPLACED DEVICES (no longer ESP32-controlled — now Pi-direct GPIO):
        #   top       -> Raspberry Pi GPIO 20  (gpio_controller.py / "gpio:top")
        #   bottom    -> Raspberry Pi GPIO 21  (gpio_controller.py / "gpio:bottom")
        #   pump      -> Raspberry Pi GPIO 23  (gpio_controller.py / "gpio:pump")
        #   flushmain -> Raspberry Pi GPIO 15  (gpio_controller.py / "gpio:flushmain")
        #   s8        -> Raspberry Pi GPIO 25  (gpio_controller.py / "gpio:s8")
        #   roof      -> RETIRED (GPIO 15 reused by flushmain)
        #   p5        -> DROPPED (backup pump; replaced by p4 on Node 2 BACK1/Relay 6)
        # =====================================================================

        # =====================================================================
        # Backward-compatible aliases (old names → new names)
        # =====================================================================
        # NOTE: 's9' -> flushmain alias removed (flushmain is now Pi GPIO, not
        # an ESP32 device). 's6' -> bottom and 's7' -> top aliases also removed.

    def _add(self, name: str, node_id: str, relay_num: int,
             relay_label: str, description: str):
        self._devices[name] = DeviceInfo(
            name=name,
            node_id=node_id,
            relay_num=relay_num,
            relay_label=relay_label,
            description=description,
        )

    def _alias(self, alias: str, target: str):
        """Create an alias that points to the same DeviceInfo."""
        if target in self._devices:
            self._devices[alias] = self._devices[target]

    def __getattr__(self, name: str) -> DeviceInfo:
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self._devices:
            return self._devices[name]
        raise AttributeError(f"Unknown device: {name}")
        
    def get(self, name: str) -> Optional[DeviceInfo]:
        return self._devices.get(name)
        
    def all_devices(self):
        """Get all device mappings (excludes aliases)."""
        primary = {}
        seen_tuples = set()
        for name, dev in self._devices.items():
            key = dev.as_tuple()
            if key not in seen_tuples:
                primary[name] = dev
                seen_tuples.add(key)
        return primary

    def get_node_devices(self, node_id: str):
        return {k: v for k, v in self.all_devices().items() if v.node_id == node_id}
        
    def print_mapping(self):
        print("\n" + "=" * 70)
        print("  DEVICE MAPPING - Project Spotless")
        print("=" * 70)
        
        for node_id in [NODE_1, NODE_2, NODE_3]:
            node_devices = self.get_node_devices(node_id)
            print(f"\n  {node_id}:")
            print("-" * 70)
            for name, device in sorted(node_devices.items(), key=lambda x: x[1].relay_num):
                print(f"    {name:10} → Relay {device.relay_num} ({device.relay_label:10}) - {device.description}")
        
        print("\n" + "=" * 70)


# =============================================================================
# Device Controller - High-level control with variable names
# =============================================================================
class DeviceHandle:
    """Handle for controlling a specific device."""
    
    def __init__(self, device_info: DeviceInfo, controller):
        self.device = device_info
        self._controller = controller
        
    def on(self) -> bool:
        logger.info(f"ON  {self.device.name} ({self.device.description})")
        return self._controller.set_relay(
            self.device.node_id, self.device.relay_num, True)
        
    def off(self) -> bool:
        logger.info(f"OFF {self.device.name} ({self.device.description})")
        return self._controller.set_relay(
            self.device.node_id, self.device.relay_num, False)
        
    def set(self, state: bool) -> bool:
        return self.on() if state else self.off()
        
    @property
    def node_id(self) -> str:
        return self.device.node_id
        
    @property
    def relay_num(self) -> int:
        return self.device.relay_num


class DeviceController:
    """
    High-level controller using friendly device names.
    
    Usage:
        dc = DeviceController(node_controller)
        dc.p1.on()         # Turn on shampoo pump
        dc.p4.on()         # Turn on disinfectant pump
        # pump / flushmain / s8 are Pi-direct GPIO now (use the GPIOController,
        # or address as "gpio:pump" / "gpio:flushmain" / "gpio:s8").
    """
    
    def __init__(self, node_controller):
        self._node_controller = node_controller
        self._devices = DeviceMap()
        self._handles = {}
        
        for name, device_info in self._devices.all_devices().items():
            self._handles[name] = DeviceHandle(device_info, node_controller)

        # No ESP32 aliases remain: s9 -> flushmain removed (flushmain is now a
        # Pi GPIO device), and s6/s7 -> bottom/top were removed earlier.

    def __getattr__(self, name: str) -> DeviceHandle:
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self._handles:
            return self._handles[name]
        raise AttributeError(f"Unknown device: {name}")
        
    def get(self, name: str) -> Optional[DeviceHandle]:
        return self._handles.get(name)
        
    def all_off(self) -> bool:
        logger.warning("ALL OFF — Turning off all devices")
        success = True
        seen = set()
        for name, handle in self._handles.items():
            key = (handle.device.node_id, handle.device.relay_num)
            if key in seen:
                continue
            seen.add(key)
            if not handle.off():
                success = False
        return success
        
    def turn_on(self, *device_names: str) -> bool:
        success = True
        for name in device_names:
            handle = self._handles.get(name)
            if handle:
                if not handle.on():
                    success = False
            else:
                logger.error(f"Unknown device: {name}")
                success = False
        return success
        
    def turn_off(self, *device_names: str) -> bool:
        success = True
        for name in device_names:
            handle = self._handles.get(name)
            if handle:
                if not handle.off():
                    success = False
            else:
                logger.error(f"Unknown device: {name}")
                success = False
        return success
        
    def toggle_devices(self, device_names: list, state: bool) -> bool:
        if state:
            return self.turn_on(*device_names)
        return self.turn_off(*device_names)
        
    def print_mapping(self):
        self._devices.print_mapping()


# =============================================================================
# Global Device Map Instance
# =============================================================================
devices = DeviceMap()


# =============================================================================
# Quick Reference Functions
# =============================================================================
def get_device(name: str) -> Optional[DeviceInfo]:
    return devices.get(name)

def get_node_relay(name: str) -> Optional[Tuple[str, int]]:
    device = devices.get(name)
    return device.as_tuple() if device else None

def print_device_mapping():
    devices.print_mapping()


if __name__ == "__main__":
    print_device_mapping()
    
    print("\n\nExample Usage:")
    print("-" * 40)
    print("from device_map import devices, DeviceController")
    print("")
    print("# Get device info")
    print(f"devices.p1       = {devices.p1}")
    print(f"devices.p3       = {devices.p3}")
    print(f"devices.s1       = {devices.s1}")
    print(f"devices.p4       = {devices.p4}")
    print("")
    print("# Pi-direct GPIO (not in device_map): pump->GPIO23, flushmain->GPIO15, s8->GPIO25")
    print("#   addressed as gpio:pump / gpio:flushmain / gpio:s8")
    print("# Displaced: top -> Pi GPIO 20, bottom -> Pi GPIO 21, p5 -> dropped (p4 took BACK1)")
