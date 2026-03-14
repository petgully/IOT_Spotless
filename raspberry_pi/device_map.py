"""
=============================================================================
Device Mapping - Project Spotless
=============================================================================
Maps friendly variable names to ESP32 node + relay combinations.

This module provides easy-to-use variable names that correspond to specific
relays on specific ESP32 nodes, matching the legacy code naming convention.

Usage:
    from device_map import devices, DeviceController
    
    # Get device info
    devices.p1  # Returns ("spotless_node1", 7) - Node 1, BACK2
    
    # With DeviceController
    dc = DeviceController(node_controller)
    dc.p1.on()   # Turn on p1 (Node 1, BACK2)
    dc.p1.off()  # Turn off p1
    dc.ro1.on()  # Turn on ro1 (Node 1, RS1&DS2)

Node/Relay Mapping:
    NODE 1 (spotless_node1):
        p1   → BACK2    (Relay 7)
        p2   → BACK1    (Relay 6)
        ro1  → RS1&DS2  (Relay 4)
        ro2  → RS2&DS1  (Relay 5)
        d1   → FP1      (Relay 3)
        p3   → P1&P2    (Relay 2)
        pump → S1       (Relay 1)

    NODE 2 (spotless_node2):
        p4   → BACK2    (Relay 7)
        p5   → BACK1    (Relay 6)
        ro3  → RS1&DS2  (Relay 4)
        ro4  → RS2&DS1  (Relay 5)
        d2   → FP1      (Relay 3)
        s7   → P1&P2    (Relay 2)
        s9   → S1       (Relay 1)

    NODE 3 (spotless_node3):
        s1   → BACK2    (Relay 7)
        s2   → BACK1    (Relay 6)
        s3   → RS1&DS2  (Relay 4)
        s4   → RS2&DS1  (Relay 5)
        s5   → FP1      (Relay 3)
        s6   → P1&P2    (Relay 2)
        s8   → S1       (Relay 1)
=============================================================================
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Relay Number Constants
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
    name: str           # Variable name (e.g., "p1", "ro1")
    node_id: str        # ESP32 node ID
    relay_num: int      # Relay number (1-7)
    relay_label: str    # Relay label (e.g., "BACK2", "RS1_DS2")
    description: str    # Human-readable description
    
    def __repr__(self):
        return f"Device({self.name}: {self.node_id} → Relay {self.relay_num} [{self.relay_label}])"
    
    def as_tuple(self) -> Tuple[str, int]:
        """Return (node_id, relay_num) tuple."""
        return (self.node_id, self.relay_num)


class DeviceMap:
    """
    Maps friendly variable names to node+relay combinations.
    """
    
    def __init__(self):
        self._devices = {}
        self._setup_mappings()
        
    def _setup_mappings(self):
        """Setup all device mappings."""
        
        # =====================================================================
        # NODE 1 Devices (spotless_node1)
        # =====================================================================
        self._add_device("p1", NODE_1, RELAY_BACK2, "BACK2", 
                        "Peristaltic Pump 1 (Node 1 BACK2)")
        self._add_device("p2", NODE_1, RELAY_BACK1, "BACK1", 
                        "Peristaltic Pump 2 (Node 1 BACK1)")
        self._add_device("ro1", NODE_1, RELAY_RS1_DS2, "RS1_DS2", 
                        "RO Solenoid 1 (Node 1 RS1&DS2)")
        self._add_device("ro2", NODE_1, RELAY_RS2_DS1, "RS2_DS1", 
                        "RO Solenoid 2 (Node 1 RS2&DS1)")
        self._add_device("d1", NODE_1, RELAY_FP1, "FP1", 
                        "Diaphragm Pump 1 (Node 1 FP1)")
        self._add_device("p3", NODE_1, RELAY_P1_P2, "P1_P2", 
                        "Pumps P1&P2 (Node 1)")
        self._add_device("pump", NODE_1, RELAY_S1_220V, "S1_220V", 
                        "Main Pump 220V (Node 1 S1)")
        
        # =====================================================================
        # NODE 2 Devices (spotless_node2)
        # =====================================================================
        self._add_device("p4", NODE_2, RELAY_BACK2, "BACK2", 
                        "Peristaltic Pump 4 (Node 2 BACK2)")
        self._add_device("p5", NODE_2, RELAY_BACK1, "BACK1", 
                        "Peristaltic Pump 5 (Node 2 BACK1)")
        self._add_device("ro3", NODE_2, RELAY_RS1_DS2, "RS1_DS2", 
                        "RO Solenoid 3 (Node 2 RS1&DS2)")
        self._add_device("ro4", NODE_2, RELAY_RS2_DS1, "RS2_DS1", 
                        "RO Solenoid 4 (Node 2 RS2&DS1)")
        self._add_device("d2", NODE_2, RELAY_FP1, "FP1", 
                        "Diaphragm Pump 2 (Node 2 FP1)")
        self._add_device("s7", NODE_2, RELAY_P1_P2, "P1_P2", 
                        "Solenoid 7 / P1&P2 (Node 2)")
        self._add_device("s9", NODE_2, RELAY_S1_220V, "S1_220V", 
                        "Solenoid 9 / 220V (Node 2 S1)")
        
        # =====================================================================
        # NODE 3 Devices (spotless_node3)
        # =====================================================================
        self._add_device("s1", NODE_3, RELAY_BACK2, "BACK2", 
                        "Solenoid 1 (Node 3 BACK2)")
        self._add_device("s2", NODE_3, RELAY_BACK1, "BACK1", 
                        "Solenoid 2 (Node 3 BACK1)")
        self._add_device("s3", NODE_3, RELAY_RS1_DS2, "RS1_DS2", 
                        "Solenoid 3 (Node 3 RS1&DS2)")
        self._add_device("s4", NODE_3, RELAY_RS2_DS1, "RS2_DS1", 
                        "Solenoid 4 (Node 3 RS2&DS1)")
        self._add_device("s5", NODE_3, RELAY_FP1, "FP1", 
                        "Solenoid 5 (Node 3 FP1)")
        self._add_device("s6", NODE_3, RELAY_P1_P2, "P1_P2", 
                        "Solenoid 6 / P1&P2 (Node 3)")
        self._add_device("s8", NODE_3, RELAY_S1_220V, "S1_220V", 
                        "Solenoid 8 / 220V (Node 3 S1)")
        
    def _add_device(self, name: str, node_id: str, relay_num: int, 
                   relay_label: str, description: str):
        """Add a device mapping."""
        self._devices[name] = DeviceInfo(
            name=name,
            node_id=node_id,
            relay_num=relay_num,
            relay_label=relay_label,
            description=description
        )
        
    def __getattr__(self, name: str) -> DeviceInfo:
        """Get device by attribute access (e.g., devices.p1)."""
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self._devices:
            return self._devices[name]
        raise AttributeError(f"Unknown device: {name}")
        
    def get(self, name: str) -> Optional[DeviceInfo]:
        """Get device by name."""
        return self._devices.get(name)
        
    def all_devices(self):
        """Get all device mappings."""
        return self._devices.copy()
        
    def get_node_devices(self, node_id: str):
        """Get all devices for a specific node."""
        return {k: v for k, v in self._devices.items() if v.node_id == node_id}
        
    def print_mapping(self):
        """Print all device mappings."""
        print("\n" + "=" * 70)
        print("  DEVICE MAPPING - Project Spotless")
        print("=" * 70)
        
        for node_id in [NODE_1, NODE_2, NODE_3]:
            node_devices = self.get_node_devices(node_id)
            print(f"\n  {node_id}:")
            print("-" * 70)
            for name, device in sorted(node_devices.items(), key=lambda x: x[1].relay_num):
                print(f"    {name:6} → Relay {device.relay_num} ({device.relay_label:10}) - {device.description}")
        
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
        """Turn the device ON."""
        logger.info(f"Turning ON {self.device.name} ({self.device.description})")
        return self._controller.set_relay(
            self.device.node_id, 
            self.device.relay_num, 
            True
        )
        
    def off(self) -> bool:
        """Turn the device OFF."""
        logger.info(f"Turning OFF {self.device.name} ({self.device.description})")
        return self._controller.set_relay(
            self.device.node_id, 
            self.device.relay_num, 
            False
        )
        
    def set(self, state: bool) -> bool:
        """Set device state."""
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
        dc.p1.on()      # Turn on p1
        dc.p1.off()     # Turn off p1
        dc.pump.on()    # Turn on main pump
    """
    
    def __init__(self, node_controller):
        self._node_controller = node_controller
        self._devices = DeviceMap()
        self._handles = {}
        
        # Create handles for all devices
        for name, device_info in self._devices.all_devices().items():
            self._handles[name] = DeviceHandle(device_info, node_controller)
            
    def __getattr__(self, name: str) -> DeviceHandle:
        """Get device handle by attribute access."""
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self._handles:
            return self._handles[name]
        raise AttributeError(f"Unknown device: {name}")
        
    def get(self, name: str) -> Optional[DeviceHandle]:
        """Get device handle by name."""
        return self._handles.get(name)
        
    def all_off(self) -> bool:
        """Turn off all devices."""
        logger.warning("ALL OFF - Turning off all devices")
        success = True
        for handle in self._handles.values():
            if not handle.off():
                success = False
        return success
        
    def turn_on(self, *device_names: str) -> bool:
        """Turn on multiple devices."""
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
        """Turn off multiple devices."""
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
        """Set multiple devices to the same state."""
        success = True
        for name in device_names:
            handle = self._handles.get(name)
            if handle:
                if not handle.set(state):
                    success = False
            else:
                logger.error(f"Unknown device: {name}")
                success = False
        return success
        
    def print_mapping(self):
        """Print device mapping."""
        self._devices.print_mapping()


# =============================================================================
# Global Device Map Instance
# =============================================================================
devices = DeviceMap()


# =============================================================================
# Quick Reference Functions
# =============================================================================
def get_device(name: str) -> Optional[DeviceInfo]:
    """Get device info by name."""
    return devices.get(name)

def get_node_relay(name: str) -> Optional[Tuple[str, int]]:
    """Get (node_id, relay_num) for a device name."""
    device = devices.get(name)
    return device.as_tuple() if device else None

def print_device_mapping():
    """Print all device mappings."""
    devices.print_mapping()


# =============================================================================
# Main - Print mapping when run directly
# =============================================================================
if __name__ == "__main__":
    print_device_mapping()
    
    print("\n\nExample Usage:")
    print("-" * 40)
    print("from device_map import devices, DeviceController")
    print("")
    print("# Get device info")
    print(f"devices.p1 = {devices.p1}")
    print(f"devices.ro1 = {devices.ro1}")
    print(f"devices.pump = {devices.pump}")
    print("")
    print("# With controller (requires NodeController)")
    print("dc = DeviceController(node_controller)")
    print("dc.p1.on()   # Turn ON p1")
    print("dc.p1.off()  # Turn OFF p1")
    print("dc.turn_on('p1', 'ro1', 'd1')  # Turn on multiple")
