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
    dc.pump.on()     # Turn on booster pump (220V)
    dc.top.on()      # Turn on flush top nozzle
    dc.flushmain.on() # Turn on autoflush gate (220V)

Node/Relay Mapping:
    NODE 1 (spotless_node1) — Container 1 system:
        p1   → BACK2    (Relay 7) - Peristaltic Pump 1 (Shampoo)
        p2   → BACK1    (Relay 6) - Peristaltic Pump 2 (Conditioner)
        ro1  → RS2&DS1  (Relay 5) - RO Solenoid 1 (Fill Container 1)
        ro2  → RS1&DS2  (Relay 4) - RO Solenoid 2 (Drain Container 1)
        d1   → FP1      (Relay 3) - Diaphragm Pump 1 (Push from Container 1)
        p3   → P1&P2    (Relay 2) - Peristaltic Pump 3 (Med Shampoo)
        pump → S1       (Relay 1) - Booster Pump 220V

    NODE 2 (spotless_node2) — Container 2 system + Autoflush:
        p4       → BACK2    (Relay 7) - Peristaltic Pump 4 (Disinfectant)
        p5       → BACK1    (Relay 6) - Peristaltic Pump 5 (Backup)
        ro3      → RS2&DS1  (Relay 5) - RO Solenoid 3 (Fill Container 2)
        ro4      → RS1&DS2  (Relay 4) - RO Solenoid 4 (Drain Container 2)
        d2       → FP1      (Relay 3) - Diaphragm Pump 2 (Push from Container 2)
        top      → P1&P2    (Relay 2) - Flush Top Nozzle
        flushmain→ S1       (Relay 1) - Autoflush Gate 220V

    NODE 3 (spotless_node3) — Bath line solenoid valves:
        s1     → BACK2    (Relay 7) - Solenoid 1 (Shampoo line gate)
        s2     → BACK1    (Relay 6) - Solenoid 2 (Common spray / anti-backflow)
        s3     → RS2&DS1  (Relay 5) - Solenoid 3 (Disinfectant line gate)
        s4     → RS1&DS2  (Relay 4) - Solenoid 4 (Common valve / anti-backflow)
        s5     → FP1      (Relay 3) - Solenoid 5 (Water line)
        bottom → P1&P2    (Relay 2) - Flush Bottom Nozzle
        s8     → S1       (Relay 1) - Main Gate 220V (bath lines)
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
        self._add("p1", NODE_1, RELAY_BACK2, "BACK2",
                  "Peristaltic Pump 1 — Shampoo")
        self._add("p2", NODE_1, RELAY_BACK1, "BACK1",
                  "Peristaltic Pump 2 — Conditioner")
        self._add("ro1", NODE_1, RELAY_RS2_DS1, "RS2_DS1",
                  "RO Solenoid 1 — Fill Container 1")
        self._add("ro2", NODE_1, RELAY_RS1_DS2, "RS1_DS2",
                  "RO Solenoid 2 — Drain Container 1")
        self._add("d1", NODE_1, RELAY_FP1, "FP1",
                  "Diaphragm Pump 1 — Push from Container 1")
        self._add("p3", NODE_1, RELAY_P1_P2, "P1_P2",
                  "Peristaltic Pump 3 — Med Shampoo")
        self._add("pump", NODE_1, RELAY_S1_220V, "S1_220V",
                  "Booster Pump 220V")

        # =====================================================================
        # NODE 2 — Container 2 system + Autoflush (spotless_node2)
        # =====================================================================
        self._add("p4", NODE_2, RELAY_BACK2, "BACK2",
                  "Peristaltic Pump 4 — Disinfectant")
        self._add("p5", NODE_2, RELAY_BACK1, "BACK1",
                  "Peristaltic Pump 5 — Backup")
        self._add("ro3", NODE_2, RELAY_RS2_DS1, "RS2_DS1",
                  "RO Solenoid 3 — Fill Container 2")
        self._add("ro4", NODE_2, RELAY_RS1_DS2, "RS1_DS2",
                  "RO Solenoid 4 — Drain Container 2")
        self._add("d2", NODE_2, RELAY_FP1, "FP1",
                  "Diaphragm Pump 2 — Push from Container 2")
        self._add("top", NODE_2, RELAY_P1_P2, "P1_P2",
                  "Flush Top Nozzle")
        self._add("flushmain", NODE_2, RELAY_S1_220V, "S1_220V",
                  "Autoflush Gate 220V")

        # =====================================================================
        # NODE 3 — Bath line solenoid valves (spotless_node3)
        # =====================================================================
        self._add("s1", NODE_3, RELAY_BACK2, "BACK2",
                  "Solenoid 1 — Shampoo line gate")
        self._add("s2", NODE_3, RELAY_BACK1, "BACK1",
                  "Solenoid 2 — Common spray / anti-backflow")
        self._add("s3", NODE_3, RELAY_RS2_DS1, "RS2_DS1",
                  "Solenoid 3 — Disinfectant line gate")
        self._add("s4", NODE_3, RELAY_RS1_DS2, "RS1_DS2",
                  "Solenoid 4 — Common valve / anti-backflow")
        self._add("s5", NODE_3, RELAY_FP1, "FP1",
                  "Solenoid 5 — Water line")
        self._add("bottom", NODE_3, RELAY_P1_P2, "P1_P2",
                  "Flush Bottom Nozzle")
        self._add("s8", NODE_3, RELAY_S1_220V, "S1_220V",
                  "Main Gate 220V — Bath lines")

        # =====================================================================
        # Backward-compatible aliases (old names → new names)
        # =====================================================================
        self._alias("s6", "bottom")
        self._alias("s7", "top")
        self._alias("s9", "flushmain")

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
        dc.pump.on()       # Turn on booster pump
        dc.top.on()        # Turn on flush top nozzle
        dc.flushmain.on()  # Turn on autoflush gate
    """
    
    def __init__(self, node_controller):
        self._node_controller = node_controller
        self._devices = DeviceMap()
        self._handles = {}
        
        for name, device_info in self._devices.all_devices().items():
            self._handles[name] = DeviceHandle(device_info, node_controller)

        # Also register aliases
        for alias in ["s6", "s7", "s9"]:
            dev = self._devices.get(alias)
            if dev:
                target_name = dev.name
                if target_name in self._handles:
                    self._handles[alias] = self._handles[target_name]

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
    print(f"devices.top      = {devices.top}")
    print(f"devices.bottom   = {devices.bottom}")
    print(f"devices.flushmain= {devices.flushmain}")
    print(f"devices.s8       = {devices.s8}")
    print("")
    print("# Backward-compatible aliases")
    print(f"devices.s6       = {devices.s6}  (alias for 'bottom')")
    print(f"devices.s7       = {devices.s7}  (alias for 'top')")
    print(f"devices.s9       = {devices.s9}  (alias for 'flushmain')")
